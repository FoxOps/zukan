"""Cardmarket (EUR). Game providers bring its prices: Scryfall and TCGdex include them,
and the public price guide files (`app.games.cardmarket`) add lowest offers."""

from typing import Any

from app.games.base import registry


class CardmarketSource:
    id = "cardmarket"
    name = "Cardmarket"
    currency = "EUR"

    def link(self, game_id: str, market_id: Any, lang: str) -> str | None:
        # The game's URL segment ("Magic") comes from its provider's `cardmarket_path`.
        path = getattr(registry().get(game_id), "cardmarket_path", None)
        if not path or not market_id:
            return None
        # Cardmarket redirects product ids to the product page.
        return f"https://www.cardmarket.com/{lang}/{path}/Products?idProduct={market_id}"


source = CardmarketSource()
