"""CardNexus (EUR), a European marketplace: its lowest listing as trend and low. Its daily
price files also bring Cardmarket and TCGplayer prices of the printings no other source
priced today. Needs `TCG_APITOKEN_PRICES_CARDNEXUS` (`app.sources.cardnexus`)."""

from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.games.base import PriceQuote
from app.prices.base import MarketTarget
from app.sources import cardnexus


class CardNexusPrices:
    id = "cardnexus"
    name = "CardNexus"
    currency = "EUR"

    @property
    def games(self) -> set[str]:
        from app.games.base import registry

        if not cardnexus.token():
            return set()
        return {g for g in registry() if cardnexus.their_games(g)}

    def link(self, game_id: str, market_id: Any, lang: str) -> str | None:
        return cardnexus.link(market_id, lang)

    def fetch(
        self, http: httpx.AsyncClient, game_id: str, targets: list[MarketTarget]
    ) -> AsyncIterator[list[PriceQuote]]:
        return cardnexus.fetch_prices(http, game_id, targets)


source = CardNexusPrices()
