"""Cardmarket's public data files, for game providers.

Cardmarket publishes, per game, a daily product list and price guide on a public download
bucket (Magic = 1, Pokémon = 6, Riftbound = 22, Sorcery = 25). They are plain file
downloads, not the website, so fetching them once a day cannot get an address blocked.

Price guide entries hold `trend`, `low` (lowest offer), `avg` and `avg1`/`avg7`/`avg30`,
plus the same fields with a `-foil` (or `-holo` for Pokémon) suffix for the foil version.
"""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx

from app.core.http import get_with_retry
from app.games.base import CatalogBatch, PriceQuote, PrintingData

DOWNLOAD_URL = "https://downloads.s3.cardmarket.com/productCatalog"

Guide = dict[str, Any]


async def products(http: httpx.AsyncClient, game: int) -> list[dict[str, Any]]:
    response = await get_with_retry(
        http, f"{DOWNLOAD_URL}/productList/products_singles_{game}.json"
    )
    return response.json()["products"]


async def price_guide(http: httpx.AsyncClient, game: int) -> dict[int, Guide]:
    """Price guide entries by Cardmarket product id."""
    response = await get_with_retry(http, f"{DOWNLOAD_URL}/priceGuide/price_guide_{game}.json")
    return {g["idProduct"]: g for g in response.json()["priceGuides"]}


def first_price(*values: Any) -> Decimal | None:
    """First given price; 0 means no data in the price guide."""
    return next((Decimal(str(v)) for v in values if v), None)


def prices(guide: Guide, suffix: str = "") -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """(trend, low, avg) of one version. Products too new for a trend fall back to the
    recent averages, then to the lowest offer."""
    trend = first_price(
        guide.get(f"trend{suffix}"),
        guide.get(f"avg7{suffix}"),
        guide.get(f"avg30{suffix}"),
        guide.get(f"avg{suffix}"),
        guide.get(f"low{suffix}"),
    )
    return trend, first_price(guide.get(f"low{suffix}")), first_price(guide.get(f"avg{suffix}"))


def name_key(name: str) -> str:
    """Card name for matching across sources: no accents, case or punctuation."""
    stripped = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", stripped.casefold()).strip()


def match_products(
    catalog: CatalogBatch,
    products: list[dict[str, Any]],
    guides: dict[int, Guide],
    expansions: dict[int, list[str]],
    suffix: Callable[[str], str],
    order: Callable[[PrintingData], Any] = lambda p: p.external_id,
) -> list[PriceQuote]:
    """Price quotes for catalog printings from Cardmarket's product list and price guide,
    for games whose products carry no collector number. Matched printings also get their
    Cardmarket product id (`market_ids`, page link).

    Products are matched by expansion and card name. `expansions` maps known expansion
    ids to our set codes (several for an expansion grouping the promos of several sets);
    other expansions go to the free set sharing the most card names. When one name has
    several products in an expansion (alternate arts, box toppers), they are paired in
    product id order with the printings of that name sorted by `order`. `suffix(finish)`
    is the price guide field suffix of a finish ("" or "-foil")."""
    ours: dict[tuple[str, str], list[PrintingData]] = defaultdict(list)
    for card in catalog.cards:
        for printing in card.printings:
            ours[(printing.set_external_id, name_key(card.name))].append(printing)
    for printings in ours.values():
        printings.sort(key=order)

    by_expansion: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for product in sorted(products, key=lambda p: p["idProduct"]):
        by_expansion[product["idExpansion"]].append(product)

    mapped = {expansion: list(codes) for expansion, codes in expansions.items()}
    set_names: dict[str, set[str]] = defaultdict(set)
    for set_code, key in ours:
        set_names[set_code].add(key)
    taken = {code for codes in mapped.values() for code in codes}
    # Largest overlaps first, so a small expansion reprinting a few cards of a set (a
    # starter deck) does not take the set from its main expansion.
    pairs = sorted(
        (
            (len(names & set_names[code]), expansion, code)
            for expansion, items in by_expansion.items()
            if expansion not in mapped
            for names in [{name_key(p["name"]) for p in items}]
            for code in set_names
            if code not in taken
        ),
        key=lambda pair: (-pair[0], pair[1], pair[2]),
    )
    for overlap, expansion, code in pairs:
        if overlap and expansion not in mapped and code not in taken:
            mapped[expansion] = [code]
            taken.add(code)

    quotes = []
    for expansion, items in by_expansion.items():
        set_codes = mapped.get(expansion)
        if not set_codes:
            continue
        same_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for product in items:
            same_name[name_key(product["name"])].append(product)
        for key, matches in same_name.items():
            printings = [p for code in set_codes for p in ours.get((code, key), [])]
            for product, printing in zip(matches, printings, strict=False):
                printing.attributes.setdefault("market_ids", {})["cardmarket"] = product[
                    "idProduct"
                ]
                guide = guides.get(product["idProduct"])
                if guide is None:
                    continue
                for finish in printing.finishes:
                    trend, low, avg = prices(guide, suffix(finish))
                    quotes.append(
                        PriceQuote(
                            printing.set_external_id,
                            printing.external_id,
                            finish,
                            trend=trend,
                            low=low,
                            avg=avg,
                            source="cardmarket",
                        )
                    )
    return quotes
