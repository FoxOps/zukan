"""TCGplayer (USD), the North American market. Game providers bring its prices (Scryfall,
TCGdex): market price as trend, lowest listing as low, median listing as average.
tcgcsv's daily files (`app.sources.tcgcsv`) price the printings they did not."""

from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.games.base import PriceQuote
from app.prices.base import MarketTarget
from app.sources import tcgcsv


class TcgplayerSource:
    id = "tcgplayer"
    name = "TCGplayer"
    currency = "USD"

    @property
    def games(self) -> set[str]:
        from app.games.base import registry

        return {g for g in registry() if tcgcsv.game_key(tcgcsv.source, g) is not None}

    def link(self, game_id: str, market_id: Any, lang: str) -> str | None:
        return f"https://www.tcgplayer.com/product/{market_id}" if market_id else None

    def fetch(
        self, http: httpx.AsyncClient, game_id: str, targets: list[MarketTarget]
    ) -> AsyncIterator[list[PriceQuote]]:
        return tcgcsv.fetch_prices(http, game_id, targets)


source = TcgplayerSource()
