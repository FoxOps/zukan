"""Official game color symbols (mana, energy types, elements), downloaded once.

Stored as `{game}/symbols/{color}.{svg|png}` under `settings.image_dir` (the games of a
group share the group's folder, `picture_game`), where a file put by hand (svg, png or
webp) is never replaced. Downloaded or own files win over the ones
shipped with Zukan (copied to `default/{game}/symbols/`), which stay as fallback. The API fetches
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
from app.games.base import ColorDef, picture_game, registry
from app.services import layout

log = logging.getLogger(__name__)


def _folder(game_id: str) -> Path:
    return layout.game_folder(get_settings().image_dir, picture_game(game_id), layout.SYMBOLS)


def symbol_file(game_id: str, code: str) -> Path | None:
    provider = registry().get(game_id)
    color = next((c for c in provider.colors if c.code == code), None) if provider else None
    if color is None:
        return None
    if (own := layout.own_picture(_folder(provider.id), color.code)) is not None:
        return own
    if color.icon_file is not None:
        # The copy in `default/` first, the package file if it is not there yet.
        root = get_settings().image_dir
        folder = layout.default_folder(root, picture_game(provider.id), layout.SYMBOLS)
        copy = folder / color.icon_file.name
        if copy.is_file():
            return copy
        if color.icon_file.is_file():
            return color.icon_file
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
        # The games of a group share their symbols.
        if picture_game(provider.id) == provider.id
        for color in provider.colors
        # A shipped symbol is only the fallback of a source's (`symbol_file`).
        if color.icon_url and layout.own_picture(_folder(provider.id), color.code) is None
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
