"""Cardmarket product ids for games whose own data has none (Pokémon China).

Cardmarket's public product list carries no collector number and no expansion name: only
the expansion id and the English card name ("Nidorina [Fetch Family | Sharp Fang]"). The
mainland Chinese printings are paired with it by English card name (`match_products`):
each Cardmarket expansion goes to the set sharing most of its names.

Candidate expansions are the ones no other game sharing the Cardmarket game uses (the
international and Japanese sets hold the same cards under the same English names, and
their printings already carry Cardmarket ids), added since Cardmarket started listing
Chinese cards, and sharing most of the set's names. Prices then come from the price
guide (`app.prices.cardmarket`) like any printing with a product id.
"""

import logging
import re
from collections import defaultdict
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.games import cardmarket
from app.games.base import CardData, CatalogBatch, GameProvider, PrintingData, registry
from app.models import Card, CardSet, Printing

log = logging.getLogger(__name__)

# Cardmarket lists Chinese cards in expansions of their own since 2024; older expansions
# with the same names are international or Japanese ones nothing links to yet.
FIRST_ADDED = "2024-01-01"
# Share of a set's (translated) names an expansion must hold to be paired with it, and
# the fewest names (small promo sets share a name or two with any expansion).
MIN_SHARE = 0.8
MIN_NAMES = 5
# Share of the expansion's names found in the set (an expansion of other cards that
# happens to hold a small set's Pokémon, e.g. code cards of Eevee products).
MIN_EXPANSION_SHARE = 0.15

_UPDATE = text(
    "UPDATE printing SET attributes = jsonb_set(attributes, '{market_ids}', "
    "coalesce(attributes -> 'market_ids', '{}'::jsonb) || "
    "jsonb_build_object('cardmarket', CAST(:product AS integer))) WHERE id = :id"
)


def _number_order(printing: PrintingData) -> tuple[int, str]:
    digits = re.match(r"\d+", printing.external_id)
    return (int(digits.group()) if digits else 1 << 30, printing.external_id)


def link(
    printings: list[tuple[str, str, str]],
    products: list[dict[str, Any]],
    claimed: set[int],
) -> dict[tuple[str, str], int]:
    """Cardmarket product id per (set external id, printing external id), for printings
    given as (set external id, printing external id, English card name)."""
    used = {p["idExpansion"] for p in products if p["idProduct"] in claimed}
    first: dict[int, str] = {}
    for product in products:
        added = product.get("dateAdded") or ""
        expansion = product["idExpansion"]
        first[expansion] = min(first.get(expansion, added), added)
    candidates = [
        p
        for p in products
        if p["idExpansion"] not in used and first[p["idExpansion"]] >= FIRST_ADDED
    ]
    by_name: dict[str, list[PrintingData]] = defaultdict(list)
    for set_id, printing_id, name in printings:
        by_name[name].append(PrintingData(printing_id, set_id))
    batch = CatalogBatch(
        cards=[CardData(name, name, printings=items) for name, items in by_name.items()]
    )
    cardmarket.match_products(
        batch,
        candidates,
        {},
        {},
        lambda finish: "",
        order=_number_order,
        key=cardmarket.pokemon_name_key,
        min_share=MIN_SHARE,
        min_names=MIN_NAMES,
        min_expansion_share=MIN_EXPANSION_SHARE,
        strict=True,
    )
    return {
        (p.set_external_id, p.external_id): p.attributes["market_ids"]["cardmarket"]
        for card in batch.cards
        for p in card.printings
        if "market_ids" in p.attributes
    }


async def link_cardmarket(
    session: AsyncSession, http: httpx.AsyncClient, provider: GameProvider
) -> int:
    """Stores Cardmarket product ids on the game's printings; returns how many changed."""
    game = provider.cardmarket_guide
    others = [
        g
        for g, p in registry().items()
        if g != provider.id and getattr(p, "cardmarket_guide", None) == game
    ]
    market_id = Printing.attributes["market_ids"]["cardmarket"].astext
    claimed = {
        int(value)
        for value in await session.scalars(
            select(market_id)
            .join(CardSet, Printing.set_id == CardSet.id)
            .where(CardSet.game_id.in_(others), market_id.is_not(None))
            .distinct()
        )
        if value.isdigit()
    }
    rows = (
        await session.execute(
            select(Printing.id, CardSet.external_id, Printing.external_id, Card.name, market_id)
            .join(CardSet, Printing.set_id == CardSet.id)
            .join(Card, Printing.card_id == Card.id)
            .where(CardSet.game_id == provider.id)
        )
    ).all()
    products = await cardmarket.products(http, game)
    found = link([(s, p, name) for _, s, p, name, _ in rows], products, claimed)
    changed = [
        {"id": pid, "product": found[(s, p)]}
        for pid, s, p, _, current in rows
        if (s, p) in found and current != str(found[(s, p)])
    ]
    if changed:
        await session.execute(_UPDATE, changed)
        await session.commit()
    log.info(
        "Cardmarket ids for %s: %d printings of %d linked, %d new",
        provider.id,
        len(found),
        len(rows),
        len(changed),
    )
    return len(changed)
