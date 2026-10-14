"""TCGplayer (USD), the North American market. Game providers bring its prices (Scryfall,
TCGdex): market price as trend, lowest listing as low, median listing as average."""

from typing import Any


class TcgplayerSource:
    id = "tcgplayer"
    name = "TCGplayer"
    currency = "USD"

    def link(self, game_id: str, market_id: Any, lang: str) -> str | None:
        return f"https://www.tcgplayer.com/product/{market_id}" if market_id else None


source = TcgplayerSource()
