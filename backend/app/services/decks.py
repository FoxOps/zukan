"""Decks module: owned copies allocated to decks.

A decklist (`DeckCard`) never changes the collection. Allocating sets owned copies of a
collection item aside for one deck (`DeckAllocation`): the item keeps its quantity, and
copies allocated to any deck are no longer available to the others. Allocations only
grow while their collection items are locked (`SELECT ... FOR UPDATE`), and collection
changes lowering a quantity lock the item too (their UPDATE) before trimming the
allocations to it (`fit_allocations`), so concurrent edits cannot allocate more copies
than owned."""

from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CollectionItem, Deck, DeckAllocation, DeckCard, Printing


class AllocationError(Exception):
    pass


@dataclass
class CardStock:
    """Copies of a card for one deck: asked for, owned, allocated."""

    requested: int = 0
    owned: int = 0
    # Allocated to this deck, and to all the user's decks (this one included).
    allocated: int = 0
    allocated_all: int = 0
    # Collection items (printing, finish, condition, language) with free copies: the
    # user chooses one when there are several.
    free_items: int = 0
    # Per printing: copies allocated to this deck, and owned copies no deck holds.
    allocated_by_printing: dict[int, int] = field(default_factory=dict)
    available_by_printing: dict[int, int] = field(default_factory=dict)

    @property
    def available(self) -> int:
        """Owned copies no deck holds."""
        return self.owned - self.allocated_all

    @property
    def missing(self) -> int:
        """Copies the user would still need to get."""
        return max(0, self.requested - self.allocated - self.available)

    @property
    def status(self) -> str:
        if self.requested and self.allocated >= self.requested:
            return "allocated"
        return "missing" if self.missing else "owned"


async def requested(session: AsyncSession, deck_id: int, card_id: int) -> int:
    """Copies of a card the deck asks for, all sections together."""
    total = await session.scalar(
        select(func.sum(DeckCard.quantity)).where(
            DeckCard.deck_id == deck_id, DeckCard.card_id == card_id
        )
    )
    return total or 0


def _of_card(card_ids: Iterable[int]):
    return CollectionItem.printing_id.in_(
        select(Printing.id).where(Printing.card_id.in_(set(card_ids)))
    )


async def allocated_by_item(session: AsyncSession, item_ids: Iterable[int]) -> dict[int, int]:
    """Copies of each item allocated to any deck."""
    rows = await session.execute(
        select(DeckAllocation.item_id, func.sum(DeckAllocation.quantity))
        .where(DeckAllocation.item_id.in_(set(item_ids)))
        .group_by(DeckAllocation.item_id)
    )
    return {item_id: int(total) for item_id, total in rows}


async def stock(session: AsyncSession, deck: Deck, card_ids: Iterable[int]) -> dict[int, CardStock]:
    """Copies of each card for the deck (its cards loaded)."""
    card_ids = set(card_ids)
    result = {card_id: CardStock() for card_id in card_ids}
    for entry in deck.cards:
        if entry.card_id in result:
            result[entry.card_id].requested += entry.quantity
    if not card_ids:
        return result
    owned = await session.execute(
        select(CollectionItem.id, Printing.card_id, Printing.id, CollectionItem.quantity)
        .join(Printing)
        .where(CollectionItem.user_id == deck.user_id, Printing.card_id.in_(card_ids))
    )
    card_of: dict[int, int] = {}
    printing_of: dict[int, int] = {}
    free: dict[int, int] = {}
    for item_id, card_id, printing_id, quantity in owned:
        card_of[item_id] = card_id
        printing_of[item_id] = printing_id
        free[item_id] = quantity
        result[card_id].owned += quantity
    allocations = await session.execute(
        select(DeckAllocation.item_id, DeckAllocation.deck_id, DeckAllocation.quantity).where(
            DeckAllocation.item_id.in_(card_of)
        )
    )
    for item_id, deck_id, quantity in allocations:
        card = result[card_of[item_id]]
        card.allocated_all += quantity
        free[item_id] -= quantity
        if deck_id == deck.id:
            card.allocated += quantity
            by_printing = card.allocated_by_printing
            by_printing[printing_of[item_id]] = by_printing.get(printing_of[item_id], 0) + quantity
    for item_id, left in free.items():
        card = result[card_of[item_id]]
        if left > 0:
            card.free_items += 1
            available = card.available_by_printing
            available[printing_of[item_id]] = available.get(printing_of[item_id], 0) + left
    return result


def line_allocations(
    lines: list[tuple[int | None, int]], allocated_by_printing: dict[int, int]
) -> list[int]:
    """Copies allocated to each line (printing or None for any, quantity) of one card:
    lines of a printing take its allocated copies first, lines of any printing share
    what is left (copies of other printings included), in order."""
    left = dict(allocated_by_printing)
    result = [0] * len(lines)
    for i, (printing_id, quantity) in enumerate(lines):
        if printing_id is not None:
            result[i] = min(quantity, left.get(printing_id, 0))
            left[printing_id] = left.get(printing_id, 0) - result[i]
    rest = sum(max(0, n) for n in left.values())
    for i, (printing_id, quantity) in enumerate(lines):
        if printing_id is None:
            result[i] = min(quantity, rest)
            rest -= result[i]
    return result


def line_printings(
    lines: list[tuple[int | None, int]], allocated_by_printing: dict[int, int]
) -> list[list[tuple[int | None, int]]]:
    """Each line's copies by printing: a line of a printing is all of that printing; a
    line of any printing gets the allocated copies lines of their printing leave (as in
    `line_allocations`), then None for the copies not allocated."""
    left = dict(allocated_by_printing)
    for printing_id, quantity in lines:
        if printing_id is not None:
            left[printing_id] = left.get(printing_id, 0) - quantity
    result: list[list[tuple[int | None, int]]] = []
    for printing_id, quantity in lines:
        if printing_id is not None:
            result.append([(printing_id, quantity)])
            continue
        parts: list[tuple[int | None, int]] = []
        for other in sorted(left):
            take = min(quantity, left[other])
            if take > 0:
                parts.append((other, take))
                left[other] -= take
                quantity -= take
        if quantity:
            parts.append((None, quantity))
        result.append(parts)
    return result


@dataclass
class ItemStock:
    item: CollectionItem
    # Copies allocated to this deck, and to any deck.
    allocated: int
    allocated_all: int

    @property
    def free(self) -> int:
        return self.item.quantity - self.allocated_all


async def items(
    session: AsyncSession, deck: Deck, card_id: int, item_id: int | None = None, lock=False
) -> list[ItemStock]:
    """The user's collection items of a card, with their allocations (locked with
    `lock`, in id order so concurrent callers do not deadlock)."""
    query = (
        select(CollectionItem)
        .where(CollectionItem.user_id == deck.user_id, _of_card([card_id]))
        .order_by(CollectionItem.id)
    )
    if item_id is not None:
        query = query.where(CollectionItem.id == item_id)
    if lock:
        query = query.with_for_update()
    found = list(await session.scalars(query.execution_options(populate_existing=True)))
    totals = await allocated_by_item(session, (i.id for i in found))
    here = dict(
        (
            await session.execute(
                select(DeckAllocation.item_id, DeckAllocation.quantity).where(
                    DeckAllocation.deck_id == deck.id,
                    DeckAllocation.item_id.in_([i.id for i in found]),
                )
            )
        ).all()
    )
    return [ItemStock(i, here.get(i.id, 0), totals.get(i.id, 0)) for i in found]


async def allocate(
    session: AsyncSession, deck: Deck, card_id: int, count: int, item_id: int | None = None
) -> int:
    """Set `count` owned copies of a card aside for the deck, from one item or the items
    with the most free copies. Returns the copies now allocated here. Does not commit."""
    if count <= 0:
        raise AllocationError("Allocate at least one copy")
    wanted = await requested(session, deck.id, card_id)
    if wanted == 0:
        raise AllocationError("This card is not in the deck")
    held = await items(session, deck, card_id, item_id, lock=True)
    if item_id is not None and not held:
        raise AllocationError("Collection item not found")
    here = await _allocated_here(session, deck.id, card_id)
    if here + count > wanted:
        raise AllocationError(f"The deck asks for {wanted} copies, {here} already allocated")
    free = sum(max(0, s.free) for s in held)
    if count > free:
        raise AllocationError(f"Only {free} owned copies are available")
    # Copies of the printings deck lines ask for, still to allocate: taken first.
    short = await _printings_short(session, deck.id, card_id, held)
    taken: dict[int, int] = {}
    left = count
    ordered = sorted(held, key=lambda s: -s.free)
    # Copies of the printings lines ask for (up to what they lack), then any copies.
    for preferred in (True, False):
        for s in ordered:
            room = s.free - taken.get(s.item.id, 0)
            if preferred:
                room = min(room, short.get(s.item.printing_id, 0))
            take = min(left, room)
            if take <= 0:
                continue
            taken[s.item.id] = taken.get(s.item.id, 0) + take
            short[s.item.printing_id] = short.get(s.item.printing_id, 0) - take
            left -= take
    for item_id, take in taken.items():
        stmt = insert(DeckAllocation).values(deck_id=deck.id, item_id=item_id, quantity=take)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[DeckAllocation.deck_id, DeckAllocation.item_id],
                set_={"quantity": DeckAllocation.quantity + take},
            )
        )
    return here + count


async def _printings_short(
    session: AsyncSession, deck_id: int, card_id: int, held: list[ItemStock]
) -> dict[int, int]:
    """Per printing deck lines ask for: copies not allocated here yet."""
    rows = await session.execute(
        select(DeckCard.printing_id, func.sum(DeckCard.quantity))
        .where(
            DeckCard.deck_id == deck_id,
            DeckCard.card_id == card_id,
            DeckCard.printing_id.is_not(None),
        )
        .group_by(DeckCard.printing_id)
    )
    short = {printing_id: int(total) for printing_id, total in rows}
    for s in held:
        if s.item.printing_id in short:
            short[s.item.printing_id] -= s.allocated
    return short


async def _allocated_here(session: AsyncSession, deck_id: int, card_id: int) -> int:
    total = await session.scalar(
        select(func.sum(DeckAllocation.quantity)).where(
            DeckAllocation.deck_id == deck_id,
            DeckAllocation.item_id.in_(select(CollectionItem.id).where(_of_card([card_id]))),
        )
    )
    return total or 0


async def release(
    session: AsyncSession, deck: Deck, card_id: int, count: int, item_id: int | None = None
) -> int:
    """Give back `count` allocated copies of a card (latest allocations first). Returns
    the copies still allocated here. Does not commit."""
    if count <= 0:
        raise AllocationError("Release at least one copy")
    query = (
        select(DeckAllocation)
        .where(
            DeckAllocation.deck_id == deck.id,
            DeckAllocation.item_id.in_(select(CollectionItem.id).where(_of_card([card_id]))),
        )
        .order_by(DeckAllocation.id.desc())
        .with_for_update()
    )
    if item_id is not None:
        query = query.where(DeckAllocation.item_id == item_id)
    rows = list(await session.scalars(query))
    held = sum(r.quantity for r in rows)
    if count > held:
        raise AllocationError(f"Only {held} copies are allocated")
    await _take_back(session, rows, count)
    return await _allocated_here(session, deck.id, card_id)


async def _take_back(session: AsyncSession, rows: list[DeckAllocation], count: int) -> None:
    for row in rows:
        if count <= 0:
            break
        take = min(count, row.quantity)
        if take == row.quantity:
            await session.execute(delete(DeckAllocation).where(DeckAllocation.id == row.id))
        else:
            await session.execute(
                update(DeckAllocation)
                .where(DeckAllocation.id == row.id)
                .values(quantity=DeckAllocation.quantity - take)
            )
        count -= take
    await session.flush()


async def release_excess(session: AsyncSession, deck: Deck, card_ids: Iterable[int]) -> None:
    """Release copies allocated beyond what the deck asks for (card removed, quantity
    lowered). Does not commit."""
    for card_id in set(card_ids):
        here = await _allocated_here(session, deck.id, card_id)
        extra = here - await requested(session, deck.id, card_id)
        if extra > 0:
            await release(session, deck, card_id, extra)


async def fit_allocations(session: AsyncSession, item_ids: Iterable[int]) -> int:
    """After collection quantities went down: trim the items' allocations (latest first)
    to the copies left. Returns the copies released. Does not commit."""
    released = 0
    for item_id in set(item_ids):
        quantity = await session.scalar(
            select(CollectionItem.quantity).where(CollectionItem.id == item_id)
        )
        rows = list(
            await session.scalars(
                select(DeckAllocation)
                .where(DeckAllocation.item_id == item_id)
                .order_by(DeckAllocation.id.desc())
                .with_for_update()
            )
        )
        extra = sum(r.quantity for r in rows) - (quantity or 0)
        if extra > 0:
            await _take_back(session, rows, extra)
            released += extra
    return released


async def move_allocations(session: AsyncSession, from_item: int, to_item: int) -> None:
    """Allocations of an item merged into another (catalog printing merge). Does not
    commit; the old item's rows go when it is deleted."""
    rows = await session.execute(
        select(DeckAllocation.deck_id, DeckAllocation.quantity).where(
            DeckAllocation.item_id == from_item
        )
    )
    for deck_id, quantity in rows.all():
        stmt = insert(DeckAllocation).values(deck_id=deck_id, item_id=to_item, quantity=quantity)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[DeckAllocation.deck_id, DeckAllocation.item_id],
                set_={"quantity": DeckAllocation.quantity + quantity},
            )
        )


async def move_lines(session: AsyncSession, from_printing: int, to_printing: int) -> None:
    """Deck lines asking for a printing merged into another (catalog printing merge):
    they ask for the new one, added to a line already asking for it; a printing of
    another card turns them into "any printing". Does not commit."""
    to_card = await session.scalar(select(Printing.card_id).where(Printing.id == to_printing))
    rows = await session.execute(
        select(
            DeckCard.id, DeckCard.deck_id, DeckCard.card_id, DeckCard.section, DeckCard.quantity
        ).where(DeckCard.printing_id == from_printing)
    )
    for line_id, deck_id, card_id, section, quantity in rows.all():
        target = to_printing if card_id == to_card else None
        same = await session.scalar(
            select(DeckCard.id).where(
                DeckCard.deck_id == deck_id,
                DeckCard.card_id == card_id,
                DeckCard.section == section,
                DeckCard.printing_id.is_not_distinct_from(target),
            )
        )
        if same is None:
            await session.execute(
                update(DeckCard).where(DeckCard.id == line_id).values(printing_id=target)
            )
        else:
            await session.execute(
                update(DeckCard)
                .where(DeckCard.id == same)
                .values(quantity=DeckCard.quantity + quantity)
            )
            await session.execute(delete(DeckCard).where(DeckCard.id == line_id))


async def set_line(
    session: AsyncSession,
    deck: Deck,
    card_id: int,
    section: str,
    printing_id: int | None,
    quantity: int,
) -> None:
    """Set a deck line's quantity (0 removes it). Does not commit."""
    if quantity == 0:
        await session.execute(
            delete(DeckCard).where(
                DeckCard.deck_id == deck.id,
                DeckCard.card_id == card_id,
                DeckCard.section == section,
                DeckCard.printing_id.is_not_distinct_from(printing_id),
            )
        )
        return
    stmt = insert(DeckCard).values(
        deck_id=deck.id,
        card_id=card_id,
        section=section,
        printing_id=printing_id,
        quantity=quantity,
    )
    await session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_deck_card_deck_id_card_id_section_printing_id",
            set_={"quantity": quantity},
        )
    )
