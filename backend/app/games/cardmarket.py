"""Cardmarket's public data files, for game providers.

Cardmarket publishes, per game, a daily product list and price guide on a public download
bucket (Magic = 1, Pokémon = 6, Sorcery = 25). They are plain file downloads, not the
website, so fetching them once a day cannot get an address blocked.

Price guide entries hold `trend`, `low` (lowest offer), `avg` and `avg1`/`avg7`/`avg30`,
plus the same fields with a `-foil` (or `-holo` for Pokémon) suffix for the foil version.
"""

from decimal import Decimal
from typing import Any

import httpx

from app.core.http import get_with_retry

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
