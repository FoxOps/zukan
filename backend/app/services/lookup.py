"""Cards the scanner read but the catalog lacks (a set newer than the last catalog sync,
a failed sync): looked up at the game's source and stored, so the scan finds them.

Only for games the text clearly belongs to (or the game chosen in the app), through the
provider's optional `lookup(http, hints) -> CatalogBatch | None`. Misses are remembered
for an hour, so a card the source does not have costs one request, not one per frame.
"""

import logging
import time

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.games.base import GameProvider, OcrHints, OcrLine
from app.services.catalog import CatalogWriter

log = logging.getLogger(__name__)

MISS_TTL = 3600.0
_misses: dict[tuple, float] = {}


def _key(game_id: str, hints: OcrHints) -> tuple:
    return (game_id, hints.set_code, hints.collector_number, hints.name, hints.lang)


def can_look_up(provider: GameProvider, hints: OcrHints) -> bool:
    return hasattr(provider, "lookup") and bool(
        (hints.set_code and hints.collector_number) or hints.name
    )


async def look_up(
    session: AsyncSession,
    http: httpx.AsyncClient,
    providers: list[GameProvider],
    lines: list[OcrLine],
    chosen: bool,
) -> bool:
    """Fetch and store the scanned card from its game's source. `chosen`: the game was
    picked in the app (else only games whose markers are in the text are tried). True
    when something was stored."""
    for provider in providers:
        hints = provider.parse_ocr(lines)
        if not (chosen or hints.recognized) or not can_look_up(provider, hints):
            continue
        key = _key(provider.id, hints)
        if time.monotonic() - _misses.get(key, -MISS_TTL) < MISS_TTL:
            continue
        try:
            batch = await provider.lookup(http, hints)
        except httpx.HTTPError as exc:
            log.warning("Lookup of %s in %s failed: %s", hints, provider.id, exc)
            batch = None
        if batch is None or not batch.cards:
            _misses[key] = time.monotonic()
            continue
        writer = CatalogWriter(session, provider.id)
        await writer.load_sets()
        await writer.write(batch)
        await session.commit()
        log.info(
            "Added %s from %s after a scan: %s",
            ", ".join(c.name for c in batch.cards),
            provider.id,
            hints,
        )
        return True
    return False
