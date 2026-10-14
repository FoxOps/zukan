"""Price source plugin contract.

A price source is a market (Cardmarket, TCGplayer...) registered under the
`fudabako.prices` entry point group. It names the market, its currency and how to link
to a product page. Prices reach it two ways:

- game providers tag the quotes found in their own data with the source id (Scryfall
  gives Cardmarket and TCGplayer prices) and list it in their `price_sources`;
- a source with its own API implements `fetch`: the daily price job then calls it for
  every game in `games`, with the game's printings and their market ids.

Market product ids are stored per printing in `attributes["market_ids"][source id]`.
Adding a market is a new plugin; core code, the web UI and the app only use this
interface.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from importlib.metadata import entry_points
from typing import Any, Protocol, runtime_checkable

ENTRY_POINT_GROUP = "fudabako.prices"


@dataclass(frozen=True)
class MarketTarget:
    """A printing to price, for sources with their own API."""

    set_external_id: str
    printing_external_id: str
    finishes: tuple[str, ...]
    # Product ids per source (`attributes["market_ids"]`).
    market_ids: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class PriceSource(Protocol):
    """Optional members:
    - `games: set[str]` and `fetch(http, game_id, targets) -> AsyncIterator[list[PriceQuote]]`
      for sources with their own API (quotes tagged with this source's id)."""

    id: str
    name: str
    # ISO 4217 code of the prices.
    currency: str

    def link(self, game_id: str, market_id: Any, lang: str) -> str | None:
        """URL of the product page, None when unknown."""
        ...


def fetches(source: PriceSource, game_id: str) -> bool:
    return hasattr(source, "fetch") and game_id in getattr(source, "games", set())


@lru_cache
def price_sources() -> dict[str, PriceSource]:
    sources: dict[str, PriceSource] = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        source = ep.load()
        if not isinstance(source, PriceSource):
            raise TypeError(f"Entry point {ep.name} is not a PriceSource")
        if source.id in sources:
            raise ValueError(f"Duplicate price source {source.id!r}")
        sources[source.id] = source
    return sources


def game_sources(game_id: str) -> list[PriceSource]:
    """Sources with prices for the game: the provider's, then those fetching their own."""
    from app.games.base import registry

    provider = registry().get(game_id)
    ids = list(getattr(provider, "price_sources", [])) if provider else []
    ids += [s.id for s in price_sources().values() if fetches(s, game_id) and s.id not in ids]
    return [price_sources()[i] for i in ids if i in price_sources()]


def preferred_source(game_id: str, wanted: str | None) -> PriceSource | None:
    """The user's source when the game has it, else the game's first source."""
    sources = game_sources(game_id)
    return next((s for s in sources if s.id == wanted), sources[0] if sources else None)
