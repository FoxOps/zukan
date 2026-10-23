"""Downloads both Yu-Gi-Oh! games read (YGOPRODeck's cards, YGOJSON), kept an hour so a
worker syncing the TCG then the OCG catalog fetches each once."""

import asyncio
import logging
import time
from typing import Any

import httpx

from app.games.yugioh import ygojson, ygoprodeck
from app.games.yugioh.ygojson import YgoJson

log = logging.getLogger(__name__)

TTL = 3600
_cards: tuple[float, list[dict[str, Any]]] | None = None
_ygojson: tuple[float, YgoJson | None] | None = None
_lock = asyncio.Lock()


def _fresh(entry: tuple[float, Any] | None) -> bool:
    return entry is not None and time.monotonic() - entry[0] <= TTL


async def cards(http: httpx.AsyncClient) -> list[dict[str, Any]]:
    """YGOPRODeck's card list (every TCG card, with its OCG password and Konami id)."""
    global _cards
    async with _lock:
        if not _fresh(_cards):
            _cards = (time.monotonic(), await ygoprodeck.cards(http))
        assert _cards is not None
        return _cards[1]


async def ygojson_data(http: httpx.AsyncClient) -> YgoJson | None:
    """YGOJSON's data, None while it cannot be read (asked again at the next sync)."""
    global _ygojson
    async with _lock:
        if not _fresh(_ygojson):
            try:
                _ygojson = (time.monotonic(), await ygojson.fetch(http))
            except (httpx.HTTPError, OSError, ValueError) as exc:
                log.warning("YGOJSON unavailable: %s", exc)
                return None
        assert _ygojson is not None
        return _ygojson[1]


def clear() -> None:
    global _cards, _ygojson
    _cards = _ygojson = None
