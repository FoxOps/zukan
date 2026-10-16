"""Game provider plugin contract.

Each trading card game is a provider registered under the `zukan.games` entry point
group. Providers only fetch and normalize data; core services store it. Core code and
clients only talk to this interface, so adding a game never requires changes elsewhere.
"""

import inspect
import unicodedata
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import lru_cache
from importlib.metadata import entry_points
from pathlib import Path
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
    # Symbol drawn for Zukan, shipped with the provider (used instead of `icon_url`).
    icon_file: Path | None = None


@dataclass(frozen=True)
class FinishDef:
    code: str  # stored in Printing.finishes / CollectionItem.finish
    name: str


@dataclass(frozen=True)
class RarityDef:
    """A rarity of the game, in increasing order in `GameProvider.rarities`. `code` names
    its pictogram `<provider package>/rarities/<code>.svg` (when there is one); `aliases`
    are other spellings sources use ("Super_rare", "(UR)")."""

    code: str
    name: str
    aliases: tuple[str, ...] = ()


def rarity_key(text: str) -> str:
    """Rarity spelling for matching: no case, accents, brackets, "_" or "-"."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(text.casefold().replace("_", " ").replace("-", " ").strip("() ").split())


@lru_cache(maxsize=64)
def _rarity_table(provider_id: str) -> dict[str, RarityDef]:
    table: dict[str, RarityDef] = {}
    for rarity in getattr(registry()[provider_id], "rarities", []):
        for spelling in (rarity.code, rarity.name, *rarity.aliases):
            table.setdefault(rarity_key(spelling), rarity)
    return table


def rarity_of(game_id: str, raw: str | None) -> RarityDef | None:
    """The game's rarity a stored `Printing.rarity` text stands for."""
    if not raw or game_id not in registry():
        return None
    return _rarity_table(game_id).get(rarity_key(raw))


def rarity_icon_file(game_id: str, code: str) -> Path | None:
    provider = registry().get(game_id)
    if provider is None:
        return None
    path = Path(inspect.getfile(type(provider))).parent / "rarities" / f"{code}.svg"
    return path if path.is_file() else None


@dataclass(frozen=True)
class FilterDef:
    """An advanced catalog search filter. `attribute`: a card attribute key (a string or a
    list of strings); None filters on the printings' rarity."""

    key: str
    label: str
    attribute: str | None = None


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
    # None: partial like its card. False: full printing data under a partial card (a
    # printing from another source added to an existing card).
    partial: bool | None = None


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
    # Price source (market) id, see `app.prices`.
    source: str = field(default="cardmarket", kw_only=True)


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
class PrintingRef:
    """A stored printing, as given to `fetch_cards`."""

    set_external_id: str
    external_id: str
    set_lang: str | None
    languages: tuple[str, ...]
    # Languages that already have an image URL.
    image_languages: tuple[str, ...]
    attributes: dict[str, Any]


@dataclass(frozen=True)
class CardRef:
    """A stored card to refresh from the source."""

    external_id: str
    name: str
    printings: tuple[PrintingRef, ...]


@dataclass(frozen=True)
class StoredPrinting:
    """A printing as stored (from the primary source), for secondary sources."""

    set_external_id: str
    external_id: str
    collector_number: str | None
    rarity: str | None
    artist: str | None
    card_external_id: str
    card_name: str
    image_languages: tuple[str, ...]
    market_ids: dict[str, Any]
    # Languages the printing exists in.
    languages: tuple[str, ...] = ()
    finishes: tuple[str, ...] = ()
    # The provider guessed the finishes (`attributes["finishes_guessed"]`): a source
    # listing the real versions should confirm them.
    finishes_guessed: bool = False
    # The card's rules text, for games naming its attribute (`text_attribute`).
    card_text: str | None = None


@dataclass
class CatalogIndex:
    """What the primary source stored for a game: secondary sources match their data
    against it."""

    sets: dict[str, SetData]
    printings: dict[tuple[str, str], StoredPrinting]


@dataclass(frozen=True)
class Discrepancy:
    """A field a secondary source disagrees on. `printing_external_id` None: the set."""

    set_external_id: str
    printing_external_id: str | None
    field: str
    primary: str | None
    secondary: str | None


@dataclass
class SecondaryBatch:
    # Partial cards keyed on stored external ids: only fill missing data.
    cards: list[CardData] = field(default_factory=list)
    discrepancies: list[Discrepancy] = field(default_factory=list)
    # Stored printings this source has (cross-checked).
    matched: int = 0
    # Sets this batch checked, for sources checking only some sets (gap sources): their
    # earlier disagreements elsewhere stay. None: the whole game is checked.
    checked_sets: list[str] | None = None


@runtime_checkable
class CatalogSource(Protocol):
    """A second source of a game's catalog, run after the provider's own (primary) one by
    the catalog job. It fills what the primary lacks and reports disagreements; the
    primary's values are kept."""

    id: str
    name: str

    def fetch(
        self, http: httpx.AsyncClient, index: CatalogIndex
    ) -> AsyncIterator[SecondaryBatch]: ...


def compare(
    set_ext: str,
    printing_ext: str | None,
    field: str,
    primary: Any,
    secondary: Any,
    words: bool = False,
) -> Discrepancy | None:
    """A discrepancy when both sources have a value and they differ. Case, accents,
    punctuation and spacing do not count ("Genesect EX" = "Genesect-EX"). `words`: the
    values are sets of words in any order, one may say more ("Holo Rare" = "Rare Holo",
    "Rare" = "Rare Holo EX"), as for rarity vocabularies."""
    if primary in (None, "") or secondary in (None, ""):
        return None
    if words:
        a, b = _words(primary), _words(secondary)
        same = a <= b or b <= a
    else:
        same = _squash(primary) == _squash(secondary)
    if same:
        return None
    return Discrepancy(set_ext, printing_ext, field, str(primary), str(secondary))


def _plain(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value).replace("☆", "★"))
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


def _squash(value: Any) -> str:
    """Letters, digits and symbols such as ★ or ♀, nothing else."""
    return "".join(c for c in _plain(value) if c.isalnum() or unicodedata.category(c) == "So")


def _words(value: Any) -> set[str]:
    return set("".join(c if c.isalnum() else " " for c in _plain(value)).split())


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
    - `cardmarket_path`: the game's Cardmarket URL segment ("Magic"), for links to
      product pages (`attributes["market_ids"]["cardmarket"]` of printings).
    - `short_names`: words that select the game in a catalog search ("mtg j25 158").
    - `set_aliases`: other codes people use for a set, by set code ({"001": ["ALP"]}).
    - `catalog_version` (default 1): bump it when `fetch_catalog` output changes in a way
      stored data must catch up with; the worker then syncs the catalog without waiting
      for `TCG_CATALOG_INTERVAL_HOURS`.
    - `text_attribute`: card attribute holding the rules text ("rules"), compared with
      secondary sources that have it.
    - `legal_notice`: text the publisher asks fan tools to show (web footer).
    - `source_keys`: the game's id in the generic gap-filling sources (`app.sources`),
      e.g. {"tcgcsv": 89, "apitcg": "riftbound"}; overrides those sources' own tables.
    - `filters: list[FilterDef]`: advanced catalog search filters (types, rarity...).
    - `rarities: list[RarityDef]`: the game's rarities, lowest first, with pictograms.
    - `rarity_in_printing = True`: a printing is one rarity of a collector number (Yu-Gi-Oh!):
      other sources' printings pair with ours by number and rarity.
    - `secondary_sources: list[CatalogSource]`: other sources of this game's catalog,
      cross-checked against it after each catalog sync.
    - `fetch_cards(http, cards: list[CardRef]) -> AsyncIterator[CatalogBatch]`: fetch
      these cards again (stale or incomplete data). Yielded cards keep the external ids
      of the refs; cards the source no longer has are left out."""

    id: str
    name: str
    colors: list[ColorDef]
    finishes: list[FinishDef]
    languages: list[str]
    # Price sources (`app.prices` ids) whose quotes `fetch_catalog` and `fetch_prices`
    # yield; empty when the game's data has no prices.
    price_sources: list[str]

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


ENTRY_POINT_GROUP = "zukan.games"


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
