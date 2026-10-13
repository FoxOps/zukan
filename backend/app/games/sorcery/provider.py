"""Sorcery: Contested Realm, data from https://api.sorcerytcg.com.

The API lists one printing per finish; slugs look like `{set}-{card}-{product}-{finish}`,
e.g. `001-abundance-b-f`. Printings are grouped per set, card and product so finishes
become a list.

Images: the API has none and asks that its CDN is not used to *serve* them. The card
pages of sorcerytcg.com show `{IMAGE_URL}/{slug}.png`; the image job downloads each one
once into the local cache (`cache_all_images`), and clients are only ever served the
local copy. The public Google Drive folder, whose files are named after the printing
slug, can still be imported instead (`fudabako import-images sorcery DIR`).

Prices: Cardmarket publishes daily product and price guide files per game
(Sorcery = game 25) on a public download bucket: two small files a day, no scraping.
"""

import logging
import re
import unicodedata
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any

import httpx

from app.core.http import get_with_retry
from app.games import cardmarket
from app.games.base import (
    CardData,
    CatalogBatch,
    ColorDef,
    FinishDef,
    OcrHints,
    OcrLine,
    PriceQuote,
    PriceTarget,
    PrintingData,
    SetData,
)
from app.games.cardmarket import Guide
from app.games.ocr import by_position, clean, letter_ratio
from app.models import Printing

log = logging.getLogger(__name__)

API_URL = "https://api.sorcerytcg.com/api/cards"
IMAGE_URL = "https://d27a44hjr9gen3.cloudfront.net/cards"
CARDMARKET_GAME = 25
# Element symbols of the sorcerytcg.com card gallery. The names carry a build hash: when
# the site changes them, the download fails, the UI shows colored badges and the next
# start tries again (update the names here).
SYMBOLS_URL = "https://sorcerytcg.com/_next/static/media"
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
            colors=elements,
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


def _name_key(name: str) -> str:
    """Card name for matching across sources: no accents, case or punctuation."""
    stripped = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", stripped.casefold()).strip()


def _guide_quote(set_code: str, printing_id: str, finish: str, guide: Guide) -> PriceQuote:
    trend, low, avg = cardmarket.prices(guide, "" if finish == "standard" else "-foil")
    return PriceQuote(set_code, printing_id, finish, trend=trend, low=low, avg=avg)


def match_cardmarket(
    catalog: CatalogBatch, products: list[dict[str, Any]], guides: dict[int, Guide]
) -> list[PriceQuote]:
    """Price quotes for catalog printings from Cardmarket's product list and price guide.
    Matched printings also get their `cardmarket_id` attribute (product page link).

    Products are matched by expansion and card name. When one name has several products
    in an expansion (box toppers, preconstructed decks), they are paired in order with
    the printings of that name, booster printing first."""
    ours: dict[tuple[str, str], list[PrintingData]] = defaultdict(list)
    for card in catalog.cards:
        for printing in card.printings:
            ours[(printing.set_external_id, _name_key(card.name))].append(printing)
    for printings in ours.values():
        printings.sort(key=lambda p: (p.attributes.get("product") != "Booster", p.external_id))

    by_expansion: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for product in sorted(products, key=lambda p: p["idProduct"]):
        by_expansion[product["idExpansion"]].append(product)

    expansions = dict(CARDMARKET_EXPANSIONS)
    set_names: dict[str, set[str]] = defaultdict(set)
    for set_code, key in ours:
        set_names[set_code].add(key)
    for expansion, items in sorted(by_expansion.items()):
        if expansion in expansions:
            continue
        names = {_name_key(p["name"]) for p in items}
        free = [code for code in set_names if code not in expansions.values()]
        best = max(free, key=lambda code: len(names & set_names[code]), default=None)
        if best is not None and names & set_names[best]:
            expansions[expansion] = best

    quotes = []
    for expansion, items in by_expansion.items():
        set_code = expansions.get(expansion)
        if set_code is None:
            continue
        same_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for product in items:
            same_name[_name_key(product["name"])].append(product)
        for key, matches in same_name.items():
            for product, printing in zip(matches, ours.get((set_code, key), []), strict=False):
                printing.attributes["cardmarket_id"] = product["idProduct"]
                guide = guides.get(product["idProduct"])
                if guide is not None:
                    quotes += [
                        _guide_quote(set_code, printing.external_id, finish, guide)
                        for finish in printing.finishes
                    ]
    return quotes


class SorceryProvider:
    id = "sorcery"
    name = "Sorcery: Contested Realm"
    colors = [
        ColorDef("air", "Air", "#A7C7E7", f"{SYMBOLS_URL}/wind.3clc3r7aw-53b.png"),
        ColorDef("earth", "Earth", "#8B7355", f"{SYMBOLS_URL}/earth.1ecox-b66v_sg.png"),
        ColorDef("fire", "Fire", "#D9534F", f"{SYMBOLS_URL}/fire.1-a6d1dh1sjri.png"),
        ColorDef("water", "Water", "#3B7DD8", f"{SYMBOLS_URL}/water.1t_7z-bl67xy7.png"),
    ]
    finishes = [
        FinishDef("standard", "Standard"),
        FinishDef("foil", "Foil"),
        FinishDef("rainbow", "Rainbow foil"),
    ]
    languages = ["en"]
    price_source = "cardmarket"
    cardmarket_path = "Sorcery"
    # About 1600 printings: every image is cached, not only those of owned cards.
    cache_all_images = True

    async def _catalog(self, http: httpx.AsyncClient) -> CatalogBatch:
        # Whole catalog in one call (API limit: 30 requests/minute).
        return parse_cards((await get_with_retry(http, API_URL)).json())

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
