"""Decks module: what a deck is worth, with the prices of the user's source for its game.

Copies allocated to the deck are worth what their collection item is (its manual price,
else the price of its printing and finish, as in the collection value). The other copies
the deck asks for are priced at the cheapest printing and finish they can be: the line's
printing, or any printing of the card for a line of any printing."""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CollectionItem, Deck, DeckAllocation, Printing
from app.services import decks
from app.services.collection import PricePoint, pricing, unit_price, user_prices


@dataclass
class DeckValue:
    currency: str
    # Copies allocated to the deck, and the others at their cheapest price.
    allocated: Decimal = Decimal(0)
    rest: Decimal = Decimal(0)
    # Copies without any price (counted in neither).
    unpriced: int = 0

    @property
    def total(self) -> Decimal:
        return self.allocated + self.rest


def _cheapest_by_printing(prices: dict[tuple[int, str], PricePoint]) -> dict[int, Decimal]:
    """Each printing's cheapest finish."""
    found: dict[int, Decimal] = {}
    for (printing_id, _), point in prices.items():
        if printing_id not in found or point.trend < found[printing_id]:
            found[printing_id] = point.trend
    return found


async def deck_values(
    session: AsyncSession,
    wanted: str | None,
    found: list[Deck],
    stocks: dict[int, dict[int, decks.CardStock]],
) -> dict[int, DeckValue]:
    """Value of each deck (their cards loaded), by deck id."""
    if not found:
        return {}
    card_ids = {e.card_id for d in found for e in d.cards}
    printings_of: dict[int, list[int]] = {}
    for printing_id, card_id in await session.execute(
        select(Printing.id, Printing.card_id).where(Printing.card_id.in_(card_ids))
    ):
        printings_of.setdefault(card_id, []).append(printing_id)
    allocations = list(
        await session.execute(
            select(DeckAllocation.deck_id, DeckAllocation.quantity, CollectionItem)
            .join(CollectionItem, DeckAllocation.item_id == CollectionItem.id)
            .where(DeckAllocation.deck_id.in_({d.id for d in found}))
        )
    )
    game_by_printing = {
        pid: d.game_id for d in found for e in d.cards for pid in printings_of.get(e.card_id, [])
    }
    prices = await user_prices(session, wanted, game_by_printing)
    cheapest = _cheapest_by_printing(prices)
    card_of = {pid: card_id for card_id, ids in printings_of.items() for pid in ids}

    result = {}
    for deck in found:
        chosen = pricing(deck.game_id, wanted)
        value = DeckValue(chosen.currency if chosen else "EUR")
        stock = stocks[deck.id]
        # Allocated copies, never more per card than the deck asks for.
        room = {card_id: counts.requested for card_id, counts in stock.items()}
        for deck_id, quantity, item in allocations:
            card_id = card_of.get(item.printing_id)
            if deck_id != deck.id or card_id not in room:
                continue
            quantity = min(quantity, room[card_id])
            room[card_id] -= quantity
            price = unit_price(item, prices)
            if price is None:
                value.unpriced += quantity
            else:
                value.allocated += price * quantity
        # The other copies, line by line.
        for card_id, counts in stock.items():
            lines = [(e.printing_id, e.quantity) for e in deck.cards if e.card_id == card_id]
            allocated = decks.line_allocations(lines, counts.allocated_by_printing)
            for (printing_id, quantity), done in zip(lines, allocated, strict=True):
                if quantity <= done:
                    continue
                ids = [printing_id] if printing_id else printings_of.get(card_id, [])
                price = min((cheapest[i] for i in ids if i in cheapest), default=None)
                if price is None:
                    value.unpriced += quantity - done
                else:
                    value.rest += price * (quantity - done)
        result[deck.id] = value
    return result
