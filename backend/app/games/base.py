"""Game provider plugin contract.

Each trading card game is a provider registered under the `fudabako.games` entry point
group. Providers only fetch and normalize data; core services store it. Core code and
clients only talk to this interface, so adding a game never requires changes elsewhere.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import lru_cache
from importlib.metadata import entry_points
from typing import Any, Protocol, runtime_checkable

import httpx

from app.models import Printing


@dataclass(frozen=True)
class ColorDef:
    code: str  # stored in Card.colors
    name: str
    hex: str  # UI badge color
    # Official symbol, downloaded once on first start: an image URL, optionally with a
    # (left, top, width, height) box to cut it out of a sprite sheet.
    icon_url: str | None = None
    icon_box: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class FinishDef:
    code: str  # stored in Printing.finishes / CollectionItem.finish
    name: str


@dataclass
class SetData:
    external_id: str
    code: str
    name: str
    lang: str | None = None
    release_date: date | None = None
    total: int | None = None
    icon_url: str | None = None


@dataclass
class PrintingData:
    external_id: str  # unique within its set
    set_external_id: str
    collector_number: str | None = None
    rarity: str | None = None
    artist: str | None = None
    finishes: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    # Image URL per language of the printed card.
    images: dict[str, str] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    # Printed names by language, when they differ per printing (e.g. MTG localized cards).
    names: dict[str, str] = field(default_factory=dict)


@dataclass
class CardData:
    external_id: str
    name: str
    colors: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    printings: list[PrintingData] = field(default_factory=list)
    # Names valid for every printing, by language.
    names: dict[str, str] = field(default_factory=dict)
    # Partial data only fills what is missing: stored card and printing fields are kept,
    # finishes, languages and names are merged. Used for secondary sources such as a
    # translated listing that lacks game details.
    partial: bool = False


@dataclass(frozen=True)
class PriceQuote:
    set_external_id: str
    printing_external_id: str
    finish: str
    trend: Decimal | None
    low: Decimal | None = None
    avg: Decimal | None = None
    currency: str = "EUR"


@dataclass
class CatalogBatch:
    """A chunk of catalog data. Sets referenced by printings must be in this batch or an
    earlier one. Prices found along the way are stored as today's snapshot."""

    sets: list[SetData] = field(default_factory=list)
    cards: list[CardData] = field(default_factory=list)
    prices: list[PriceQuote] = field(default_factory=list)


@dataclass(frozen=True)
class PriceTarget:
    """A printing someone owns, for providers that fetch prices card by card."""

    set_external_id: str
    printing_external_id: str
    set_lang: str | None


@dataclass(frozen=True)
class OcrLine:
    """A text line recognized on a card photo. Box coordinates are fractions of the card
    (or frame) size, 0 = left/top; unknown when the client does not send them."""

    text: str
    left: float | None = None
    top: float | None = None
    width: float | None = None
    height: float | None = None


@dataclass
class OcrHints:
    """What a provider could read from the text recognized on a card."""

    name: str | None = None
    # Other lines that may hold the name when OCR order or layout is unusual.
    other_names: list[str] = field(default_factory=list)
    set_code: str | None = None
    collector_number: str | None = None
    lang: str | None = None
    # The text looks like this game's cards (copyright line, layout markers...).
    recognized: bool = False


@runtime_checkable
class GameProvider(Protocol):
    """Optional attributes:
    - `cache_all_images = True`: the image job downloads every printing's image instead
      of only owned ones (small catalogs).
    - `cardmarket_path`: the game's Cardmarket URL segment ("Magic"); printings with a
      `cardmarket_id` attribute then link to their Cardmarket page.
    - `catalog_version` (default 1): bump it when `fetch_catalog` output changes in a way
      stored data must catch up with; the worker then syncs the catalog without waiting
      for `TCG_CATALOG_INTERVAL_HOURS`."""

    id: str
    name: str
    colors: list[ColorDef]
    finishes: list[FinishDef]
    languages: list[str]
    # Source name stored on price snapshots, None when the game has no price data.
    price_source: str | None

    def fetch_catalog(self, http: httpx.AsyncClient) -> AsyncIterator[CatalogBatch]:
        """Yield the full catalog in batches."""
        ...

    def fetch_prices(
        self, http: httpx.AsyncClient, owned: list[PriceTarget]
    ) -> AsyncIterator[list[PriceQuote]]:
        """Yield current prices in batches. Providers with bulk price data may ignore
        `owned` and return every printing. Yields nothing when the game has no prices."""
        ...

    def image_file_stems(self, printing: Printing) -> list[str]:
        """File names (without extension) matching this printing in a manually downloaded
        image folder. Empty when images are downloaded from `Printing.image_urls`."""
        ...

    def parse_ocr(self, lines: list[OcrLine]) -> OcrHints:
        """Extract name, set code, collector number and language from OCR lines."""
        ...


ENTRY_POINT_GROUP = "fudabako.games"


def catalog_version(provider: GameProvider) -> int:
    return getattr(provider, "catalog_version", 1)


@lru_cache
def registry() -> dict[str, GameProvider]:
    providers: dict[str, GameProvider] = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        provider = ep.load()
        if not isinstance(provider, GameProvider):
            raise TypeError(f"Entry point {ep.name} is not a GameProvider")
        if provider.id in providers:
            raise ValueError(f"Duplicate game id {provider.id!r}")
        providers[provider.id] = provider
    return providers


def get_provider(game_id: str) -> GameProvider:
    try:
        return registry()[game_id]
    except KeyError:
        raise KeyError(f"Unknown game {game_id!r}") from None
