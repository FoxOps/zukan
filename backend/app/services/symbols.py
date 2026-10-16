"""Official game color symbols (mana, energy types, elements), downloaded once.

Stored as `symbols/{game}/{color}.{svg|png}` under `settings.image_dir`. The API fetches
missing ones in the background on start, so a new game or color gets its symbol on the
next restart, and a failed download is retried then.
"""

import asyncio
import io
import logging
from pathlib import Path

import httpx
from PIL import Image

from app.core.config import get_settings
from app.core.http import http_client
from app.games.base import ColorDef, registry

log = logging.getLogger(__name__)

_SUFFIXES = (".svg", ".png")


def _folder(game_id: str) -> Path:
    return get_settings().image_dir / "symbols" / game_id


def symbol_file(game_id: str, code: str) -> Path | None:
    provider = registry().get(game_id)
    color = next((c for c in provider.colors if c.code == code), None) if provider else None
    if color is not None and color.icon_file is not None and color.icon_file.is_file():
        return color.icon_file
    for suffix in _SUFFIXES:
        path = _folder(game_id) / f"{code}{suffix}"
        if path.is_file():
            return path
    return None


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _to_png(data: bytes, box: tuple[int, int, int, int] | None) -> bytes:
    """A bitmap as PNG, cut out of a sprite sheet when `box` is given."""
    with Image.open(io.BytesIO(data)) as image:
        if box:
            left, top, width, height = box
            image = image.crop((left, top, left + width, top + height))
        out = io.BytesIO()
        image.save(out, "PNG")
        return out.getvalue()


async def _store(
    http: httpx.AsyncClient, game_id: str, color: ColorDef, downloads: dict[str, httpx.Response]
) -> None:
    assert color.icon_url
    # Sprite sheets are shared by several colors: download each once.
    if color.icon_url not in downloads:
        response = await http.get(color.icon_url)
        response.raise_for_status()
        downloads[color.icon_url] = response
    response = downloads[color.icon_url]
    if response.headers.get("content-type", "").startswith("image/svg"):
        data, suffix = response.content, ".svg"
    else:
        data = await asyncio.to_thread(_to_png, response.content, color.icon_box)
        suffix = ".png"
    await asyncio.to_thread(_write, _folder(game_id) / f"{color.code}{suffix}", data)


async def ensure_symbols() -> int:
    """Store the symbols that are missing; returns how many were stored."""
    missing = [
        (provider.id, color)
        for provider in registry().values()
        for color in provider.colors
        if color.icon_url and not color.icon_file and symbol_file(provider.id, color.code) is None
    ]
    if not missing:
        return 0
    stored = 0
    downloads: dict[str, httpx.Response] = {}
    async with http_client(timeout=20) as http:
        for game_id, color in missing:
            try:
                await _store(http, game_id, color, downloads)
                stored += 1
            except (httpx.HTTPError, OSError) as exc:
                log.warning("Symbol %s/%s not stored: %s", game_id, color.code, exc)
    log.info("Stored %s game symbols", stored)
    return stored
