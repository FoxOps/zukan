"""tcgcsv (https://tcgcsv.com): TCGplayer's catalog and market prices as daily JSON files
(updated about 20:00 UTC), free and without key. English cards only.

TCGplayer tiers: categories (games) > groups (sets) > products (cards, sealed) with
`extendedData` (number, rarity, rules text...) and a parallel prices file per group
(low / mid / market per version: Normal, Foil, Holofoil...).

Catalog: fills TCGplayer ids, rarities and finishes of printings missing them, and
checks names, rarities and rules text, for the sets holding such gaps. Prices: TCGplayer
quotes for printings no other source priced today (`app.prices.tcgplayer`).
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.core.http import get_with_retry
from app.core.text import plain_text
from app.games.base import CatalogIndex, PriceQuote, SecondaryBatch, SetData, registry
from app.models import CardSet
from app.prices.base import MarketTarget
from app.sources.base import (
    BoundSource,
    ExternalPrinting,
    ExternalSet,
    check_set,
    finish_codes,
    game_key,
    match_sets,
    sets_with_gaps,
    stored_by_set,
)

log = logging.getLogger(__name__)

BASE_URL = "https://tcgcsv.com/tcgplayer"
# A static file host: a short pause between files is enough.
PAUSE = 0.1
# TCGplayer category of each game we have. Others tcgcsv has, for future games
# (`/tcgplayer/categories`): Yu-Gi-Oh 2, Flesh and Blood 62, One Piece 68, Lorcana 71,
# Star Wars Unlimited 79, Pokémon Japan 85 (not English: left out).
CATEGORIES = {"mtg": 1, "pokemon": 3, "sorcery": 77, "riftbound": 89}
_TEXT_FIELDS = ("OracleText", "Description", "CardText")


def _released(value: str | None):
    return datetime.fromisoformat(value).date() if value else None


def parse_groups(raw: list[dict[str, Any]]) -> list[ExternalSet]:
    return [
        ExternalSet(
            key=g["groupId"],
            name=g["name"],
            codes=[g["abbreviation"]] if g.get("abbreviation") else [],
            release_date=_released(g.get("publishedOn")),
        )
        for g in raw
    ]


def parse_products(
    products: list[dict[str, Any]], prices: list[dict[str, Any]]
) -> list[ExternalPrinting]:
    """Cards of a group (products with card data; sealed products have none)."""
    versions: dict[int, list[str]] = {}
    for price in prices:
        versions.setdefault(price["productId"], []).append(price["subTypeName"])
    out = []
    for product in products:
        data = {e["name"]: e["value"] for e in product.get("extendedData") or []}
        if not data or not ("Number" in data or "Rarity" in data):
            continue
        image = product.get("imageUrl")
        out.append(
            ExternalPrinting(
                number=data.get("Number"),
                name=product["name"],
                rarity=data.get("Rarity"),
                image=image.replace("_200w.", "_in_1000x1000.") if image else None,
                tcgplayer_id=str(product["productId"]),
                text=plain_text(next((data[f] for f in _TEXT_FIELDS if data.get(f)), None)),
                versions=versions.get(product["productId"], []),
            )
        )
    return out


async def _json(http: httpx.AsyncClient, url: str) -> list[dict[str, Any]]:
    await asyncio.sleep(PAUSE)
    return (await get_with_retry(http, url)).json()["results"]


class TcgcsvSource:
    id = "tcgcsv"
    name = "tcgcsv (TCGplayer)"
    order = 10
    games = CATEGORIES

    def for_game(self, game_id: str) -> BoundSource | None:
        if game_key(self, game_id) is None:
            return None
        return BoundSource(self.id, self.name, game_id, self.run)

    async def run(
        self, http: httpx.AsyncClient, index: CatalogIndex, game_id: str
    ) -> AsyncIterator[SecondaryBatch]:
        gaps = sets_with_gaps(index)
        if not gaps:
            return
        category = game_key(self, game_id)
        groups = parse_groups(await _json(http, f"{BASE_URL}/{category}/groups"))
        matches = match_sets(index.sets, groups, game_id)
        stored = stored_by_set(index)
        check_text = bool(getattr(registry().get(game_id), "text_attribute", None))
        wanted = [(group, set_ext) for group, set_ext in matches.items() if set_ext in gaps]
        log.info("tcgcsv %s: %s of %s sets with gaps matched", game_id, len(wanted), len(gaps))
        for group, set_ext in wanted:
            products = await _json(http, f"{BASE_URL}/{category}/{group}/products")
            prices = await _json(http, f"{BASE_URL}/{category}/{group}/prices")
            yield check_set(
                game_id, self.id, stored[set_ext], parse_products(products, prices), check_text
            )


def _price(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value else None


async def fetch_prices(
    http: httpx.AsyncClient, game_id: str, targets: list[MarketTarget]
) -> AsyncIterator[list[PriceQuote]]:
    """TCGplayer quotes for targets with a TCGplayer id and no TCGplayer quote today:
    market price as trend, lowest listing as low, median as average."""
    category = game_key(source, game_id)
    if category is None:
        return
    wanted: dict[str, MarketTarget] = {
        str(t.market_ids["tcgplayer"]): t
        for t in targets
        if t.market_ids.get("tcgplayer") and "tcgplayer" not in t.quoted
    }
    if not wanted:
        return
    # Only the groups of sets holding such printings.
    set_ids = {t.set_external_id for t in wanted.values()}
    async with get_sessionmaker()() as session:
        rows = await session.scalars(
            select(CardSet).where(CardSet.game_id == game_id, CardSet.external_id.in_(set_ids))
        )
        ours = {
            s.external_id: SetData(s.external_id, s.code, s.name, s.lang, s.release_date)
            for s in rows
        }
    groups = parse_groups(await _json(http, f"{BASE_URL}/{category}/groups"))
    for group in match_sets(ours, groups, game_id):
        prices = await _json(http, f"{BASE_URL}/{category}/{group}/prices")
        quotes = []
        for price in prices:
            target = wanted.get(str(price["productId"]))
            if target is None:
                continue
            for finish in finish_codes(game_id, [price["subTypeName"]]):
                if finish not in target.finishes:
                    continue
                quotes.append(
                    PriceQuote(
                        target.set_external_id,
                        target.printing_external_id,
                        finish,
                        trend=_price(price.get("marketPrice")),
                        low=_price(price.get("lowPrice")),
                        avg=_price(price.get("midPrice")),
                        currency="USD",
                        source="tcgplayer",
                    )
                )
        if quotes:
            yield quotes


source = TcgcsvSource()
