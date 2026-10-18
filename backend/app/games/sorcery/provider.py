"""Sorcery: Contested Realm, data from https://api.sorcerytcg.com.

The API lists one printing per finish; slugs look like `{set}-{card}-{product}-{finish}`,
e.g. `001-abundance-b-f`. Printings are grouped per set, card and product so finishes
become a list.

Images: the API has none and asks that its CDN is not used to *serve* them. The card
pages of sorcerytcg.com show `{IMAGE_URL}/{slug}.png`; the image job downloads each one
once into the local cache (`cache_all_images`), and clients are only ever served the
local copy. The public Google Drive folder, whose files are named after the printing
slug, can still be imported instead (`zukan import-images sorcery DIR`).

Prices: Cardmarket publishes daily product and price guide files per game
(Sorcery = game 25) on a public download bucket: two small files a day, no scraping.
"""

import logging
import time
from collections.abc import AsyncIterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx

from app.core.http import get_with_retry
from app.games import cardmarket
from app.games.base import (
    CardData,
    CardRef,
    CatalogBatch,
    ColorDef,
    FilterDef,
    FinishDef,
    OcrHints,
    OcrLine,
    PriceQuote,
    PriceTarget,
    PrintingData,
    RarityDef,
    SetData,
)
from app.games.cardmarket import Guide
from app.games.ocr import by_position, clean, letter_ratio
from app.models import Printing

log = logging.getLogger(__name__)

API_URL = "https://api.sorcerytcg.com/api/cards"
LEGAL_NOTICE = (
    "Sorcery: Contested Realm is a trademark of Erik's Curiosa Limited. Zukan is not "
    "produced, endorsed, supported or affiliated with Erik's Curiosa. Card data from the "
    "official Sorcery card API."
)
IMAGE_URL = "https://d27a44hjr9gen3.cloudfront.net/cards"
CARDMARKET_GAME = 25
# Element symbols of the sorcerytcg.com card gallery. The names carry a build hash: when
# the site changes them, the download fails, the UI shows colored badges and the next
# start tries again (update the names here).
SYMBOLS_URL = "https://sorcerytcg.com/_next/static/media"
SYMBOLS = Path(__file__).parent / "symbols"
# Cardmarket expansion id -> Sorcery set code. Expansions missing here (new sets) are
# matched to the set sharing the most card names.
CARDMARKET_EXPANSIONS = {
    6771: "001",  # Alpha
    6775: "002",  # Beta
    6778: "004",  # Arthurian Legends
    6781: "005",  # Dragonlord
    6779: "006",  # Gothic
    6780: "999",  # Promo
}

_FINISHES = {"Standard": "standard", "Foil": "foil", "Rainbow": "rainbow"}
_ELEMENTS = ("air", "earth", "fire", "water")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _printing_key(slug: str) -> tuple[str, str]:
    """`001-abundance-b-f` -> set code `001`, printing id `abundance-b` (finish dropped)."""
    set_code, card_slug, product, _finish = slug.split("-")
    return set_code, f"{card_slug}-{product}"


def _preferred_slugs(slugs: dict[str, str]) -> list[str]:
    """Slugs of one printing, standard finish first (foil scans look the same, shinier)."""
    order = ["standard", "foil", "rainbow"]
    return [slugs[f] for f in sorted(slugs, key=lambda f: order.index(f) if f in order else 9)]


def _card_attributes(engine: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": engine.get("type"),
        "category": engine.get("category"),
        "rarity": engine.get("rarity"),
        "rules": engine.get("rules"),
        "cost": engine.get("cost"),
        "attack": engine.get("attack"),
        "defense": engine.get("defense"),
        "life": engine.get("life"),
        "thresholds": {e: engine.get(e) or 0 for e in _ELEMENTS},
        "subtypes": engine.get("subtypes") or [],
        "keywords": engine.get("keywords") or [],
        "back": engine.get("back"),
    }


def parse_cards(raw: list[dict[str, Any]]) -> CatalogBatch:
    batch = CatalogBatch()
    sets: dict[str, SetData] = {}
    for item in raw:
        engine = item.get("engine") or {}
        elements = [e.lower() for e in engine.get("elements") or [] if e.lower() in _ELEMENTS]
        card = CardData(
            external_id=item["slug"],
            name=item["name"],
            colors=elements or ["colorless"],
            attributes=_card_attributes(engine),
            names={"en": item["name"]},
        )
        printings: dict[tuple[str, str], PrintingData] = {}
        for raw_printing in item.get("printings") or []:
            set_info = raw_printing["set"]
            meta = raw_printing.get("meta") or {}
            set_code, printing_id = _printing_key(raw_printing["slug"])
            if set_code != set_info["code"]:
                raise ValueError(f"Unexpected Sorcery slug {raw_printing['slug']!r}")
            set_data = sets.setdefault(
                set_code,
                SetData(external_id=set_code, code=set_code, name=set_info["name"], lang="en"),
            )
            # Earliest printing date is the closest thing to a release date the API gives.
            printed = _parse_date(raw_printing.get("printedAt"))
            if printed and (set_data.release_date is None or printed < set_data.release_date):
                set_data.release_date = printed
            finish = _FINISHES.get(meta.get("finish"), str(meta.get("finish", "")).lower())
            printing = printings.get((set_code, printing_id))
            if printing is None:
                printing = printings[(set_code, printing_id)] = PrintingData(
                    external_id=printing_id,
                    set_external_id=set_code,
                    rarity=engine.get("rarity"),
                    artist=(meta.get("artist") or {}).get("name"),
                    languages=["en"],
                    attributes={
                        "product": meta.get("product"),
                        "typeline": meta.get("typeline"),
                        "flavor": meta.get("flavor"),
                        "back": meta.get("back"),
                        "slugs": {},
                    },
                )
            if finish not in printing.finishes:
                printing.finishes.append(finish)
            printing.attributes["slugs"][finish] = raw_printing["slug"]
        card.printings = list(printings.values())
        for printing in card.printings:
            slug = _preferred_slugs(printing.attributes["slugs"])[0]
            printing.images = {"en": f"{IMAGE_URL}/{slug}.png"}
        batch.cards.append(card)
    batch.sets = list(sets.values())
    return batch


def match_cardmarket(
    catalog: CatalogBatch, products: list[dict[str, Any]], guides: dict[int, Guide]
) -> list[PriceQuote]:
    """Price quotes for catalog printings from Cardmarket's product list and price guide
    (by expansion and card name, booster printing first among same names)."""
    return cardmarket.match_products(
        catalog,
        products,
        guides,
        {expansion: [code] for expansion, code in CARDMARKET_EXPANSIONS.items()},
        lambda finish: "" if finish == "standard" else "-foil",
        lambda p: (p.attributes.get("product") != "Booster", p.external_id),
    )


# Catalog kept for card refreshes: (time.monotonic() of download, catalog).
CATALOG_TTL = 3600
_cached_catalog: tuple[float, CatalogBatch] | None = None


class SorceryProvider:
    id = "sorcery"
    name = "Sorcery: Contested Realm"
    colors = [
        ColorDef("air", "Air", "#A7C7E7", f"{SYMBOLS_URL}/wind.3clc3r7aw-53b.png"),
        ColorDef("earth", "Earth", "#8B7355", f"{SYMBOLS_URL}/earth.1ecox-b66v_sg.png"),
        ColorDef("fire", "Fire", "#D9534F", f"{SYMBOLS_URL}/fire.1-a6d1dh1sjri.png"),
        ColorDef("water", "Water", "#3B7DD8", f"{SYMBOLS_URL}/water.1t_7z-bl67xy7.png"),
        # Cards without element (drawn for Zukan, scripts/draw_color_symbols.py).
        ColorDef("colorless", "Colorless", "#9CA3AF", icon_file=SYMBOLS / "colorless.svg"),
    ]
    finishes = [
        FinishDef("standard", "Standard"),
        FinishDef("foil", "Foil"),
        FinishDef("rainbow", "Rainbow foil"),
    ]
    languages = ["en"]
    price_sources = ["cardmarket"]
    rarities = [
        RarityDef("ordinary", "Ordinary"),
        RarityDef("exceptional", "Exceptional"),
        RarityDef("elite", "Elite"),
        RarityDef("unique", "Unique"),
    ]
    filters = [
        FilterDef("category", "Category", "category"),
        FilterDef("type", "Type", "type"),
        FilterDef("subtypes", "Subtype", "subtypes"),
        FilterDef("rarity", "Rarity"),
    ]
    cardmarket_path = "Sorcery"
    text_attribute = "rules"
    short_names = ["sorcery", "sor", "sct"]
    legal_notice = LEGAL_NOTICE
    # Set codes are numbers; these are the abbreviations players use.
    set_aliases = {
        "001": ["ALP", "alpha"],
        "002": ["BET", "beta"],
        "004": ["ART", "AL", "arthurian"],
        "005": ["DRL", "DL", "dragonlord"],
        "006": ["GTH", "gothic"],
        "999": ["PRO", "promo"],
    }
    # About 1600 printings: every image is cached, not only those of owned cards.
    cache_all_images = True
    # 2: image URLs (databases upgraded from 0.2 had none). 3: colorless cards.
    catalog_version = 3

    async def _catalog(self, http: httpx.AsyncClient) -> CatalogBatch:
        # Whole catalog in one call (API limit: 30 requests/minute).
        return parse_cards((await get_with_retry(http, API_URL)).json())

    async def _cached(self, http: httpx.AsyncClient) -> CatalogBatch:
        # No single card endpoint: the whole catalog (one call), kept a while so
        # refreshing cards one by one does not download it every time.
        global _cached_catalog
        if _cached_catalog is None or time.monotonic() - _cached_catalog[0] > CATALOG_TTL:
            _cached_catalog = (time.monotonic(), await self._catalog(http))
        return _cached_catalog[1]

    async def lookup(self, http: httpx.AsyncClient, hints: OcrHints) -> CatalogBatch | None:
        """A scanned card missing from the catalog, by exact name (accents, case and
        punctuation aside)."""
        if not hints.name:
            return None
        catalog = await self._cached(http)
        key = cardmarket.name_key(hints.name)
        found = [card for card in catalog.cards if cardmarket.name_key(card.name) == key]
        return CatalogBatch(sets=catalog.sets, cards=found) if found else None

    async def fetch_cards(
        self, http: httpx.AsyncClient, cards: list[CardRef]
    ) -> AsyncIterator[CatalogBatch]:
        catalog = await self._cached(http)
        wanted = {ref.external_id for ref in cards}
        found = [card for card in catalog.cards if card.external_id in wanted]
        if found:
            yield CatalogBatch(sets=catalog.sets, cards=found)

    async def _cardmarket_quotes(
        self, http: httpx.AsyncClient, catalog: CatalogBatch
    ) -> list[PriceQuote]:
        products = await cardmarket.products(http, CARDMARKET_GAME)
        guides = await cardmarket.price_guide(http, CARDMARKET_GAME)
        return match_cardmarket(catalog, products, guides)

    async def fetch_catalog(self, http: httpx.AsyncClient) -> AsyncIterator[CatalogBatch]:
        batch = await self._catalog(http)
        try:
            batch.prices = await self._cardmarket_quotes(http, batch)
        except httpx.HTTPError as exc:
            # The daily price job tries again.
            log.warning("Cardmarket price guide unavailable: %s", exc)
        yield batch

    async def fetch_prices(
        self, http: httpx.AsyncClient, owned: list[PriceTarget]
    ) -> AsyncIterator[list[PriceQuote]]:
        yield await self._cardmarket_quotes(http, await self._catalog(http))

    def image_file_stems(self, printing: Printing) -> list[str]:
        return _preferred_slugs(printing.attributes.get("slugs", {}))

    def parse_ocr(self, lines: list[OcrLine]) -> OcrHints:
        # No collector number or set code on the cards: the name (top line) is all.
        ordered = by_position([OcrLine(clean(line.text), line.left, line.top) for line in lines])
        names = [
            line.text
            for line in ordered
            if len(line.text) >= 3
            and letter_ratio(line.text) > 0.7
            and not line.text.startswith("©")
        ]
        recognized = any("Curiosa" in line.text for line in ordered)
        if not names:
            return OcrHints(lang="en", recognized=recognized)
        return OcrHints(name=names[0], other_names=names[1:3], lang="en", recognized=recognized)
