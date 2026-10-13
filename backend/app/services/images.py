"""Local card image cache.

A printing can have one image per language (`Printing.image_urls`). Images are stored
under `settings.image_dir` as `{game}/{set_id}/{printing_id}-{lang}.{ext}` (database ids
only, so no user or provider text ends up in paths). They are fetched on first view,
pre-fetched by the worker (owned printings, or every printing for small catalogs), or
imported from a folder.

Users see a card in their interface language when that scan exists, else in English,
else in Japanese, else in whatever language exists.
"""

import asyncio
import io
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.games.base import GameProvider, get_provider
from app.models import Card, CollectionItem, Printing

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
    stored: int = 0
    missing: int = 0
    failed: int = 0


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
    return f"{game_id}/{printing.set_id}/{printing.id}-{lang}{extension}"


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
        response = await http.get(url)
        response.raise_for_status()
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
    data = response.content
    if extension is None or len(data) > _MAX_IMAGE_BYTES:
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
    query = (
        select(Printing)
        .join(Card)
        .where(Card.game_id == game_id, Printing.image_urls != {})
        .order_by(Printing.id)
    )
    if not getattr(get_provider(game_id), "cache_all_images", False):
        owned = select(CollectionItem.printing_id).where(CollectionItem.quantity > 0)
        query = query.where(Printing.id.in_(owned))
    else:
        # Be gentle with servers that were not made for bulk downloads.
        concurrency = 2
    printings = (await session.scalars(query)).all()
    report = ImageReport()
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch(printing: Printing) -> None:
        languages = image_languages(printing)
        if not languages or any(cached_file(printing, lang) for lang in languages):
            return
        lang = next((lang for lang in languages if printing.image_paths.get(lang) != ""), None)
        if lang is None:
            return
        async with semaphore:
            if await download_image(http, game_id, printing, lang):
                report.stored += 1
            else:
                report.failed += 1

    await asyncio.gather(*(fetch(p) for p in printings))
    await session.commit()
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
