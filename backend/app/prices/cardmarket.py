"""Cardmarket (EUR). Game providers bring its prices: Scryfall and TCGdex include them,
and the public price guide files (`app.games.cardmarket`) add lowest offers.

Games whose provider sets `cardmarket_guide` (Cardmarket game number) and
`cardmarket_suffixes(finishes)` (finish -> price field suffix) also get the price guide
for the printings with a Cardmarket product id that their own data left unpriced today."""

import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.games import cardmarket
from app.games.base import PriceQuote, registry
from app.prices.base import MarketTarget

log = logging.getLogger(__name__)


class CardmarketSource:
    id = "cardmarket"
    name = "Cardmarket"
    currency = "EUR"

    @property
    def games(self) -> set[str]:
        return {g for g, p in registry().items() if getattr(p, "cardmarket_guide", None)}

    async def fetch(
        self, http: httpx.AsyncClient, game_id: str, targets: list[MarketTarget]
    ) -> AsyncIterator[list[PriceQuote]]:
        provider = registry()[game_id]
        wanted = [t for t in targets if t.market_ids.get(self.id) and self.id not in t.quoted]
        if not wanted:
            return
        guides = await cardmarket.price_guide(http, provider.cardmarket_guide)
        quotes: list[PriceQuote] = []
        for target in wanted:
            try:
                guide = guides.get(int(target.market_ids[self.id]))
            except (TypeError, ValueError):
                continue
            if guide is None:
                continue
            for finish, suffix in provider.cardmarket_suffixes(target.finishes).items():
                trend, low, avg = cardmarket.prices(guide, suffix)
                if trend or low or avg:
                    quotes.append(
                        PriceQuote(
                            target.set_external_id,
                            target.printing_external_id,
                            finish,
                            trend=trend,
                            low=low,
                            avg=avg,
                            source=self.id,
                        )
                    )
            if len(quotes) >= 2000:
                yield quotes
                quotes = []
        if quotes:
            yield quotes
        log.info("Cardmarket price guide %s: %s printings looked up", game_id, len(wanted))

    def link(self, game_id: str, market_id: Any, lang: str) -> str | None:
        # The game's URL segment ("Magic") comes from its provider's `cardmarket_path`.
        path = getattr(registry().get(game_id), "cardmarket_path", None)
        if not path or not market_id:
            return None
        # Cardmarket redirects product ids to the product page.
        return f"https://www.cardmarket.com/{lang}/{path}/Products?idProduct={market_id}"


source = CardmarketSource()
