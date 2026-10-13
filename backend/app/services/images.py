"""Local card image cache.

Images are stored under `settings.image_dir` as `{game}/{set_id}/{printing_id}.{ext}`
(database ids only, so no user or provider text ends up in paths). They are fetched
from `Printing.image_url` on first view, pre-fetched for owned cards by the worker, or
imported from a folder for games whose images are not downloadable (Sorcery).
"""

import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.games.base import GameProvider
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


@dataclass
class ImageReport:
    stored: int = 0
    missing: int = 0
    failed: int = 0


def image_root() -> Path:
    return get_settings().image_dir


def cached_file(printing: Printing) -> Path | None:
    if not printing.image_path:
        return None
    path = image_root() / printing.image_path
    return path if path.is_file() else None


def _relative_path(game_id: str, printing: Printing, extension: str) -> str:
    return f"{game_id}/{printing.set_id}/{printing.id}{extension}"


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


async def download_image(http: httpx.AsyncClient, game_id: str, printing: Printing) -> bool:
    """Download `printing.image_url` into the cache and set `image_path`. No commit."""
    if not printing.image_url:
        return False
    try:
        response = await http.get(printing.image_url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Image download failed for printing %s: %s", printing.id, exc)
        return False
    content_type = response.headers.get("content-type", "").split(";")[0].strip()
    extension = _EXTENSIONS.get(content_type)
    if extension is None or len(response.content) > _MAX_IMAGE_BYTES:
        log.warning("Rejected image for printing %s (%s)", printing.id, content_type)
        return False
    relative = _relative_path(game_id, printing, extension)
    await asyncio.to_thread(_write_atomic, image_root() / relative, response.content)
    printing.image_path = relative
    return True


async def get_or_fetch(
    session: AsyncSession, http: httpx.AsyncClient, printing: Printing
) -> Path | None:
    path = cached_file(printing)
    if path is not None:
        return path
    card = await session.get(Card, printing.card_id)
    if card is not None and await download_image(http, card.game_id, printing):
        await session.commit()
        return cached_file(printing)
    return None


async def cache_owned_images(
    session: AsyncSession, http: httpx.AsyncClient, game_id: str, concurrency: int = 4
) -> ImageReport:
    """Pre-fetch images of printings somebody owns."""
    owned = select(CollectionItem.printing_id).where(CollectionItem.quantity > 0)
    printings = (
        await session.scalars(
            select(Printing)
            .join(Card)
            .where(
                Card.game_id == game_id,
                Printing.id.in_(owned),
                Printing.image_url.is_not(None),
            )
        )
    ).all()
    report = ImageReport()
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch(printing: Printing) -> None:
        if cached_file(printing) is not None:
            return
        async with semaphore:
            if await download_image(http, game_id, printing):
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
    """Copy images named after `provider.image_file_stems()` from `folder` into the cache."""
    index = await asyncio.to_thread(_index_folder, folder)
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
        relative = _relative_path(provider.id, printing, source.suffix.lower())
        await asyncio.to_thread(_copy_atomic, source, image_root() / relative)
        printing.image_path = relative
        report.stored += 1
    await session.commit()
    return report
