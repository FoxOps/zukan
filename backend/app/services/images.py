"""Local card image cache.

A printing can have one image per language (`Printing.image_urls`). Images are stored
under `settings.image_dir` as `{game}/cards/{set_id}/{printing_id}-{lang}.{ext}` (database ids
only, so no user or provider text ends up in paths). They are fetched on first view,
pre-fetched by the worker (owned printings, or every printing for small catalogs), or
imported from a folder. Folder layout: `layout`.

Users see a card in their interface language when that scan exists, else in English,
else in Japanese, else in whatever language exists.
"""

import asyncio
import io
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.http import get_limited
from app.games.base import GameProvider, get_provider
from app.models import Card, CardSet, CollectionItem, Printing
from app.services import layout

log = logging.getLogger(__name__)

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/avif": ".avif",
}
_IMPORT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".avif"}
_MAX_IMAGE_BYTES = 15 * 1024 * 1024
# Lossless scans (Sorcery PNGs are ~2 MB) are stored as WebP at this width.
_REENCODE_ABOVE_BYTES = 1024 * 1024
_REENCODE_WIDTH = 745
FALLBACK_LANGUAGES = ("en", "ja")


@dataclass
class ImageReport:
    # Printings looked at; each one lands in exactly one of the counters below.
    printings: int = 0
    stored: int = 0
    # Already on disk.
    cached: int = 0
    # No image source (no URL, nothing imported).
    missing: int = 0
    # Every source answered 404 earlier: not tried again.
    refused: int = 0
    failed: int = 0
    # Set icons and card back faces downloaded.
    icons: int = 0
    backs: int = 0
    # Set icons and back faces the source did not give.
    assets_failed: int = 0


def image_root() -> Path:
    return get_settings().image_dir


def image_languages(printing: Printing, wanted: str | None = None) -> list[str]:
    """Languages to try for this printing, best first, among those with an image."""
    available = set(printing.image_urls) | {
        lang for lang, path in printing.image_paths.items() if path
    }
    order = [wanted, *FALLBACK_LANGUAGES, *sorted(available)]
    return [lang for lang in dict.fromkeys(order) if lang in available]


def has_image(printing: Printing) -> bool:
    return bool(image_languages(printing))


def cached_file(printing: Printing, lang: str) -> Path | None:
    relative = printing.image_paths.get(lang)
    if not relative:
        return None
    path = image_root() / relative
    return path if path.is_file() else None


def _relative_path(game_id: str, printing: Printing, lang: str, extension: str) -> str:
    return f"{game_id}/{layout.CARDS}/{printing.set_id}/{printing.id}-{lang}{extension}"


def _set_path(printing: Printing, lang: str, relative: str) -> None:
    # A new dict, so SQLAlchemy sees the JSONB change.
    printing.image_paths = {**printing.image_paths, lang: relative}


def _write_atomic(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(target)


def _copy_atomic(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    shutil.copyfile(source, tmp)
    tmp.replace(target)


def _shrink(data: bytes) -> bytes:
    """Card-sized WebP version of a large scan."""
    with Image.open(io.BytesIO(data)) as image:
        if image.width > _REENCODE_WIDTH:
            height = round(image.height * _REENCODE_WIDTH / image.width)
            image = image.resize((_REENCODE_WIDTH, height), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, "WEBP", quality=88, method=4)
        return out.getvalue()


async def download_image(
    http: httpx.AsyncClient, game_id: str, printing: Printing, lang: str
) -> bool:
    """Download the image of `printing` in `lang` into the cache. No commit."""
    url = printing.image_urls.get(lang)
    if not url:
        return False
    try:
        response, data = await get_limited(http, url, _MAX_IMAGE_BYTES)
    except httpx.HTTPStatusError as exc:
        log.warning("Image download failed for printing %s/%s: %s", printing.id, lang, exc)
        if 400 <= exc.response.status_code < 500:
            _set_path(printing, lang, "")  # does not exist: do not try on every view
        return False
    except httpx.HTTPError as exc:
        log.warning("Image download failed for printing %s/%s: %s", printing.id, lang, exc)
        return False
    content_type = response.headers.get("content-type", "").split(";")[0].strip()
    extension = _EXTENSIONS.get(content_type)
    if extension is None or data is None:
        log.warning("Rejected image for printing %s (%s)", printing.id, content_type)
        return False
    if len(data) > _REENCODE_ABOVE_BYTES:
        try:
            data, extension = await asyncio.to_thread(_shrink, data), ".webp"
        except OSError as exc:
            log.warning("Unreadable image for printing %s: %s", printing.id, exc)
            return False
    relative = _relative_path(game_id, printing, lang, extension)
    await asyncio.to_thread(_write_atomic, image_root() / relative, data)
    _set_path(printing, lang, relative)
    return True


# Small pictures besides card fronts (set icons, MTG back faces): SVG allowed.
_ASSET_EXTENSIONS = {**_EXTENSIONS, "image/svg+xml": ".svg"}
# Assets that could not be downloaded, not tried again before this many seconds.
_ASSET_RETRY = 3600.0
_asset_failures: dict[str, float] = {}


def asset_file(stem: str) -> Path | None:
    """Cached asset `stem` (relative path without extension), any extension."""
    target = image_root() / stem
    for path in sorted(target.parent.glob(f"{target.name}.*")) if target.parent.is_dir() else []:
        if path.suffix in _ASSET_EXTENSIONS.values():
            return path
    return None


async def cached_asset(http: httpx.AsyncClient, url: str | None, stem: str) -> Path | None:
    """A picture from `url`, downloaded once to `stem.<ext>` under the image folder, so
    clients never load it from the source."""
    if (existing := asset_file(stem)) is not None:
        return existing
    if not url or time.monotonic() - _asset_failures.get(stem, -_ASSET_RETRY) < _ASSET_RETRY:
        return None
    try:
        response, data = await get_limited(
            http, url, _MAX_IMAGE_BYTES, headers={"Accept": "image/*"}
        )
    except httpx.HTTPError as exc:
        log.warning("Download of %s failed: %s", url, exc)
        _asset_failures[stem] = time.monotonic()
        return None
    content_type = response.headers.get("content-type", "").split(";")[0].strip()
    extension = _ASSET_EXTENSIONS.get(content_type)
    if extension is None or data is None:
        log.warning("Rejected %s (%s)", url, content_type)
        _asset_failures[stem] = time.monotonic()
        return None
    path = image_root() / f"{stem}{extension}"
    await asyncio.to_thread(_write_atomic, path, data)
    return path


def back_stem(game_id: str, printing: Printing) -> str:
    return f"{game_id}/{layout.CARDS}/{printing.set_id}/{printing.id}-back"


def set_icon_stem(card_set: CardSet) -> str:
    return f"{card_set.game_id}/{layout.SETS}/{card_set.id}"


async def get_or_fetch(
    session: AsyncSession, http: httpx.AsyncClient, printing: Printing, wanted: str | None
) -> Path | None:
    """Best cached image for `wanted`, downloading it (or a fallback) when needed."""
    card: Card | None = None
    for lang in image_languages(printing, wanted):
        path = cached_file(printing, lang)
        if path is not None:
            return path
        if printing.image_paths.get(lang) == "":
            continue
        card = card or await session.get(Card, printing.card_id)
        if card is None:
            return None
        downloaded = await download_image(http, card.game_id, printing, lang)
        await session.commit()
        if downloaded:
            return cached_file(printing, lang)
    return None


async def cache_images(
    session: AsyncSession, http: httpx.AsyncClient, game_id: str, concurrency: int = 4
) -> ImageReport:
    """Pre-fetch the default image (English, else Japanese, else any) of owned printings,
    or of every printing when the provider sets `cache_all_images`."""
    query = select(Printing).join(Card).where(Card.game_id == game_id).order_by(Printing.id)
    if not getattr(get_provider(game_id), "cache_all_images", False):
        owned = select(CollectionItem.printing_id).where(CollectionItem.quantity > 0)
        query = query.where(Printing.id.in_(owned))
    else:
        # Be gentle with servers that were not made for bulk downloads.
        concurrency = 2
    printings = (await session.scalars(query)).all()
    report = ImageReport(printings=len(printings))
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch(printing: Printing) -> None:
        languages = image_languages(printing)
        if not languages:
            # No source known: the catalog has no image URL and nothing was imported.
            report.missing += 1
            return
        if any(cached_file(printing, lang) for lang in languages):
            report.cached += 1
            return
        lang = next((lang for lang in languages if printing.image_paths.get(lang) != ""), None)
        if lang is None:
            report.refused += 1
            return
        async with semaphore:
            if await download_image(http, game_id, printing, lang):
                report.stored += 1
            else:
                report.failed += 1

    await asyncio.gather(*(fetch(p) for p in printings))
    await session.commit()

    # Back faces of the same printings, and every set icon.
    async def asset(url: str | None, stem: str) -> bool:
        if not url or asset_file(stem) is not None:
            return False
        async with semaphore:
            stored = await cached_asset(http, url, stem) is not None
        report.assets_failed += not stored
        return stored

    backs = await asyncio.gather(
        *(asset(p.attributes.get("back_image_url"), back_stem(game_id, p)) for p in printings)
    )
    report.backs = sum(backs)
    sets = (await session.scalars(select(CardSet).where(CardSet.game_id == game_id))).all()
    icons = await asyncio.gather(*(asset(s.icon_url, set_icon_stem(s)) for s in sets))
    report.icons = sum(icons)
    if report.missing and report.missing == len(printings):
        log.warning(
            "No image source for any of %s %s printings: run the catalog job first",
            len(printings),
            game_id,
        )
    return report


def _index_folder(folder: Path) -> dict[str, Path]:
    if not folder.is_dir():
        raise FileNotFoundError(f"{folder} is not a directory")
    index: dict[str, Path] = {}
    for path in folder.rglob("*"):
        if path.suffix.lower() in _IMPORT_SUFFIXES and path.is_file():
            index.setdefault(path.stem.lower(), path)
    return index


async def import_image_folder(
    session: AsyncSession, provider: GameProvider, folder: Path
) -> ImageReport:
    """Copy images named after `provider.image_file_stems()` from `folder` into the cache
    (as the game's first language)."""
    index = await asyncio.to_thread(_index_folder, folder)
    lang = provider.languages[0]
    printings = await session.scalars(
        select(Printing).join(Card).where(Card.game_id == provider.id)
    )
    report = ImageReport()
    for printing in printings:
        source = next(
            (index[s.lower()] for s in provider.image_file_stems(printing) if s.lower() in index),
            None,
        )
        if source is None:
            report.missing += 1
            continue
        relative = _relative_path(provider.id, printing, lang, source.suffix.lower())
        await asyncio.to_thread(_copy_atomic, source, image_root() / relative)
        _set_path(printing, lang, relative)
        report.stored += 1
    await session.commit()
    return report
