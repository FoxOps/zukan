"""Official game symbols, downloaded once: colors (mana, energy types, elements) and the
symbols card texts write as tokens (`SymbolDef`: "{T}", "{2}").

Stored as `{game}/symbols/{color code or symbol key}.{svg|png}` under
`settings.image_dir` (the games of a group share the group's folder, `picture_game`),
where a file put by hand (svg, png or webp) is never replaced. Downloaded or own files
win over the ones shipped with Zukan (copied to `default/{game}/symbols/`), which stay as
fallback. The API fetches missing ones in the background on start, so a new game or
symbol gets its picture on the next restart, and a failed download is retried then.
"""

import asyncio
import io
import logging
from pathlib import Path

import httpx
from PIL import Image

from app.core.config import get_settings
from app.core.http import http_client
from app.games.base import ColorDef, SymbolDef, picture_game, registry
from app.services import layout

log = logging.getLogger(__name__)


def _folder(game_id: str) -> Path:
    return layout.game_folder(get_settings().image_dir, picture_game(game_id), layout.SYMBOLS)


def _picture(game_id: str, name: str, icon_file: Path | None) -> Path | None:
    if (own := layout.own_picture(_folder(game_id), name)) is not None:
        return own
    if icon_file is not None:
        # The copy in `default/` first, the package file if it is not there yet.
        root = get_settings().image_dir
        folder = layout.default_folder(root, picture_game(game_id), layout.SYMBOLS)
        copy = folder / icon_file.name
        if copy.is_file():
            return copy
        if icon_file.is_file():
            return icon_file
    return None


def symbol_file(game_id: str, code: str) -> Path | None:
    """The picture of a game color."""
    provider = registry().get(game_id)
    color = next((c for c in provider.colors if c.code == code), None) if provider else None
    if color is None:
        return None
    return _picture(provider.id, color.code, color.icon_file)


def text_symbols(game_id: str) -> list[SymbolDef]:
    provider = registry().get(game_id)
    return list(getattr(provider, "symbols", [])) if provider else []


def text_symbol_file(game_id: str, key: str) -> Path | None:
    """The picture of a text symbol (`SymbolDef.key`): its color's for color symbols."""
    symbol = next((s for s in text_symbols(game_id) if s.key == key), None)
    if symbol is None:
        return None
    if symbol.color is not None:
        return symbol_file(game_id, symbol.color)
    return _picture(game_id, symbol.key, symbol.icon_file)


def _write(path: Path, data: bytes) -> None:
    layout.write_atomic(path, data)


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
    http: httpx.AsyncClient,
    game_id: str,
    name: str,
    url: str,
    box: tuple[int, int, int, int] | None,
    downloads: dict[str, httpx.Response],
) -> None:
    # Sprite sheets are shared by several colors: download each once.
    if url not in downloads:
        response = await http.get(url)
        response.raise_for_status()
        downloads[url] = response
    response = downloads[url]
    if response.headers.get("content-type", "").startswith("image/svg"):
        data, suffix = response.content, ".svg"
    else:
        data = await asyncio.to_thread(_to_png, response.content, box)
        suffix = ".png"
    await asyncio.to_thread(_write, _folder(game_id) / f"{name}{suffix}", data)


def _missing() -> list[tuple[str, str, str, tuple[int, int, int, int] | None]]:
    """(game, file name, URL, sprite box) of the symbols to download."""
    wanted: list[tuple[str, str, str, tuple[int, int, int, int] | None]] = []
    for provider in registry().values():
        # The games of a group share their symbols.
        if picture_game(provider.id) != provider.id:
            continue
        found: set[str] = set()
        defs: list[ColorDef | SymbolDef] = [*provider.colors, *text_symbols(provider.id)]
        for symbol in defs:
            name = symbol.code if isinstance(symbol, ColorDef) else symbol.key
            box = symbol.icon_box if isinstance(symbol, ColorDef) else None
            # A shipped symbol is only the fallback of a source's (`symbol_file`).
            if (
                symbol.icon_url
                and name not in found
                and layout.own_picture(_folder(provider.id), name) is None
            ):
                found.add(name)
                wanted.append((provider.id, name, symbol.icon_url, box))
    return wanted


async def ensure_symbols() -> int:
    """Store the symbols that are missing; returns how many were stored."""
    missing = _missing()
    if not missing:
        return 0
    stored = 0
    downloads: dict[str, httpx.Response] = {}
    async with http_client(timeout=20) as http:
        for game_id, name, url, box in missing:
            try:
                await _store(http, game_id, name, url, box, downloads)
                stored += 1
            except (httpx.HTTPError, OSError) as exc:
                log.warning("Symbol %s/%s not stored: %s", game_id, name, exc)
    log.info("Stored %s game symbols", stored)
    return stored
