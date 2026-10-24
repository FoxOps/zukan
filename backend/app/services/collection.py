"""Collection stock: adjustments with an undo-able history, prices and value.

Stock changes are single atomic upserts (`quantity = quantity + delta`) guarded by the
`quantity >= 0` check constraint, so concurrent scans from a phone and edits from the
web never lose updates or go negative.

Unit price of an item: its manual price, else the latest API price of its printing and
finish from the user's price source for that game (`app.prices.base.preferred_source`).
API prices are not per condition or language. Values are per currency: prices of
different sources are never added up.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.games.base import get_provider
from app.models import CardSet, CollectionItem, Condition, PriceSnapshot, Printing, StockTransaction
from app.prices.base import preferred_source, price_sources


class StockError(Exception):
    """Invalid stock change (unknown variant, quantity below zero...)."""


@dataclass(frozen=True)
class Variant:
    finish: str
    condition: str
    language: str


@dataclass
class PricePoint:
    trend: Decimal
    date: date
    low: Decimal | None = None
    currency: str = "EUR"
    source: str = "cardmarket"


@dataclass(frozen=True)
class Pricing:
    """The price source used for a game and its currency."""

    source: str
    currency: str


def pricing(game_id: str, wanted: str | None) -> Pricing | None:
    source = preferred_source(game_id, wanted)
    return Pricing(source.id, source.currency) if source else None


async def game_of(session: AsyncSession, printing: Printing) -> str:
    return await session.scalar(select(CardSet.game_id).where(CardSet.id == printing.set_id))


def check_variant(game_id: str, printing: Printing, variant: Variant) -> None:
    provider = get_provider(game_id)
    finishes = printing.finishes or [f.code for f in provider.finishes]
    if variant.finish not in finishes:
        raise StockError(f"Finish {variant.finish!r} does not exist for this printing")
    if variant.language not in provider.languages:
        raise StockError(f"Language {variant.language!r} is not supported for {provider.name}")
    if variant.condition not in Condition.__members__:
        raise StockError(f"Unknown condition {variant.condition!r}")


async def adjust(
    session: AsyncSession,
    user_id: int,
    printing: Printing,
    variant: Variant,
    delta: int,
    source: str,
    game_id: str | None = None,
) -> tuple[CollectionItem, StockTransaction]:
    """Add (or remove, with a negative delta) copies. Does not commit."""
    if delta == 0:
        raise StockError("Quantity change cannot be zero")
    check_variant(game_id or await game_of(session, printing), printing, variant)
    if delta > 0:
        stmt = insert(CollectionItem).values(
            user_id=user_id,
            printing_id=printing.id,
            finish=variant.finish,
            condition=variant.condition,
            language=variant.language,
            quantity=delta,
        )
        item_id = await session.scalar(
            stmt.on_conflict_do_update(
                index_elements=[
                    CollectionItem.user_id,
                    CollectionItem.printing_id,
                    CollectionItem.finish,
                    CollectionItem.condition,
                    CollectionItem.language,
                ],
                set_={"quantity": CollectionItem.quantity + delta, "updated_at": func.now()},
            ).returning(CollectionItem.id)
        )
    else:
        # Check constraints apply to the proposed insert row, so removals are an UPDATE
        # guarded in its WHERE clause.
        item_id = await session.scalar(
            update(CollectionItem)
            .where(
                CollectionItem.user_id == user_id,
                CollectionItem.printing_id == printing.id,
                CollectionItem.finish == variant.finish,
                CollectionItem.condition == variant.condition,
                CollectionItem.language == variant.language,
                CollectionItem.quantity >= -delta,
            )
            .values(quantity=CollectionItem.quantity + delta, updated_at=func.now())
            .returning(CollectionItem.id)
        )
        if item_id is None:
            raise StockError("Not enough copies to remove")
    transaction = StockTransaction(user_id=user_id, item_id=item_id, delta=delta, source=source)
    session.add(transaction)
    await session.flush()
    item = await session.get(CollectionItem, item_id, populate_existing=True)
    return item, transaction


async def set_quantity(
    session: AsyncSession, item: CollectionItem, quantity: int, source: str
) -> StockTransaction | None:
    """Set an item's quantity, recording the difference. Does not commit."""
    delta = quantity - item.quantity
    if delta == 0:
        return None
    result = await session.execute(
        update(CollectionItem)
        .where(CollectionItem.id == item.id, CollectionItem.quantity == item.quantity)
        .values(quantity=quantity)
    )
    if result.rowcount != 1:
        raise StockError("Quantity changed meanwhile, reload and retry")
    transaction = StockTransaction(
        user_id=item.user_id, item_id=item.id, delta=delta, source=source
    )
    session.add(transaction)
    await session.flush()
    await session.refresh(item)
    return transaction


async def undo(session: AsyncSession, user_id: int, transaction_id: int) -> CollectionItem:
    """Revert a stock change. Does not commit."""
    transaction = await session.scalar(
        select(StockTransaction).where(
            StockTransaction.id == transaction_id, StockTransaction.user_id == user_id
        )
    )
    if transaction is None:
        raise LookupError("Transaction not found")
    marked = await session.execute(
        update(StockTransaction)
        .where(StockTransaction.id == transaction.id, StockTransaction.undone.is_(False))
        .values(undone=True)
    )
    if marked.rowcount != 1:
        raise StockError("Already undone")
    reverted = await session.execute(
        update(CollectionItem)
        .where(
            CollectionItem.id == transaction.item_id,
            CollectionItem.quantity >= transaction.delta,
        )
        .values(quantity=CollectionItem.quantity - transaction.delta, updated_at=func.now())
    )
    if reverted.rowcount != 1:
        raise StockError("Copies were removed since, cannot undo this addition")
    item = await session.get(CollectionItem, transaction.item_id, populate_existing=True)
    return item


async def latest_prices(
    session: AsyncSession, printing_ids: Iterable[int], source: str, on: date | None = None
) -> dict[tuple[int, str], PricePoint]:
    """Latest trend price (and lowest offer) of one source per (printing, finish),
    optionally as of a date."""
    ids = list(set(printing_ids))
    if not ids:
        return {}
    query = (
        select(
            PriceSnapshot.printing_id,
            PriceSnapshot.finish,
            PriceSnapshot.trend,
            PriceSnapshot.date,
            PriceSnapshot.low,
            PriceSnapshot.currency,
        )
        .ext(distinct_on(PriceSnapshot.printing_id, PriceSnapshot.finish))
        .where(
            PriceSnapshot.printing_id.in_(ids),
            PriceSnapshot.source == source,
            PriceSnapshot.trend.is_not(None),
        )
        .order_by(PriceSnapshot.printing_id, PriceSnapshot.finish, PriceSnapshot.date.desc())
    )
    if on is not None:
        query = query.where(PriceSnapshot.date <= on)
    rows = await session.execute(query)
    return {
        (pid, finish): PricePoint(trend, day, low, currency, source)
        for pid, finish, trend, day, low, currency in rows
    }


async def user_prices(
    session: AsyncSession,
    wanted: str | None,
    game_by_printing: dict[int, str],
    on: date | None = None,
) -> dict[tuple[int, str], PricePoint]:
    """Latest prices of printings of any games, each from the user's source for its game."""
    by_source: dict[str, list[int]] = {}
    for printing_id, game_id in game_by_printing.items():
        if (chosen := pricing(game_id, wanted)) is not None:
            by_source.setdefault(chosen.source, []).append(printing_id)
    found: dict[tuple[int, str], PricePoint] = {}
    for source, ids in by_source.items():
        found |= await latest_prices(session, ids, source, on)
    return found


# Periods of the trend arrows, and the change below which a price counts as stable.
TREND_PERIODS = {"d1": 1, "d7": 7, "d30": 30}
TREND_STABLE = Decimal("0.02")


@dataclass(frozen=True)
class Trend:
    direction: str  # "up", "down" or "flat"
    change: float  # relative change, 0.1 = +10 %


def trend_between(past: PricePoint | None, now: PricePoint | None) -> Trend | None:
    """Direction of the market price from `past` to `now`; None without two prices."""
    if past is None or now is None or past.date >= now.date or not past.trend:
        return None
    change = (now.trend - past.trend) / past.trend
    direction = "flat" if abs(change) < TREND_STABLE else "up" if change > 0 else "down"
    return Trend(direction, float(round(change, 4)))


async def price_trends(
    session: AsyncSession,
    wanted: str | None,
    game_by_printing: dict[int, str],
    now: dict[tuple[int, str], PricePoint],
    today: date | None = None,
) -> dict[tuple[int, str], dict[str, Trend | None]]:
    """Trend of each (printing, finish) of `now` over the last day, week and month, from
    the price history of the user's source (None where the history is too short)."""
    today = today or date.today()
    found: dict[tuple[int, str], dict[str, Trend | None]] = {key: {} for key in now}
    for period, days in TREND_PERIODS.items():
        past = await user_prices(session, wanted, game_by_printing, today - timedelta(days=days))
        for key, point in now.items():
            found[key][period] = trend_between(past.get(key), point)
    return found


def unit_price(item: CollectionItem, prices: dict[tuple[int, str], PricePoint]) -> Decimal | None:
    if item.manual_price is not None:
        return item.manual_price
    point = prices.get((item.printing_id, item.finish))
    return point.trend if point else None


async def owned_items(
    session: AsyncSession, user_id: int, game_id: str | None = None
) -> list[tuple[CollectionItem, str]]:
    """Items with copies, with their game."""
    query = (
        select(CollectionItem, CardSet.game_id)
        .join(Printing, CollectionItem.printing_id == Printing.id)
        .join(CardSet, Printing.set_id == CardSet.id)
        .where(CollectionItem.user_id == user_id, CollectionItem.quantity > 0)
    )
    if game_id:
        query = query.where(CardSet.game_id == game_id)
    return [(item, game) for item, game in (await session.execute(query)).all()]


@dataclass
class GameValue:
    game_id: str
    currency: str
    total: Decimal
    quantity: int
    priced: int
    unpriced: int


async def value_by_game(session: AsyncSession, user_id: int, wanted: str) -> list[GameValue]:
    rows = await owned_items(session, user_id)
    prices = await user_prices(session, wanted, {item.printing_id: game for item, game in rows})
    games: dict[str, GameValue] = {}
    for item, game_id in rows:
        chosen = pricing(game_id, wanted)
        currency = chosen.currency if chosen else "EUR"
        value = games.setdefault(game_id, GameValue(game_id, currency, Decimal(0), 0, 0, 0))
        price = unit_price(item, prices)
        value.quantity += item.quantity
        if price is None:
            value.unpriced += item.quantity
        else:
            value.priced += item.quantity
            value.total += price * item.quantity
    return sorted(games.values(), key=lambda v: v.game_id)


async def value_history(
    session: AsyncSession,
    user_id: int,
    wanted: str,
    game_id: str | None,
    start: date,
    end: date,
) -> tuple[str, list[tuple[date, Decimal]]]:
    """Currency and daily value of the current holdings, priced with each day's latest
    known prices.

    Quantities are today's: the curve shows how prices moved for what is owned now.
    Without a game, games priced in another currency than the user's source are left
    out."""
    currency = price_sources()[wanted].currency if wanted in price_sources() else "EUR"
    if game_id is not None and (chosen := pricing(game_id, wanted)) is not None:
        currency = chosen.currency
    rows = await owned_items(session, user_id, game_id)
    source_of = {
        item.printing_id: chosen.source
        for item, game in rows
        if (chosen := pricing(game, wanted)) is not None and chosen.currency == currency
    }
    items = [item for item, _ in rows if item.printing_id in source_of]
    days = [start + timedelta(days=n) for n in range((end - start).days + 1)]
    if not items:
        return currency, [(day, Decimal(0)) for day in days]
    # Prices on the first day, then every later snapshot in order.
    first = await user_prices(
        session, wanted, {i.printing_id: g for i, g in rows if i.printing_id in source_of}, start
    )
    current = {k: p.trend for k, p in first.items()}
    snapshots = await session.execute(
        select(
            PriceSnapshot.date,
            PriceSnapshot.printing_id,
            PriceSnapshot.finish,
            PriceSnapshot.trend,
            PriceSnapshot.source,
        )
        .where(
            PriceSnapshot.printing_id.in_(source_of),
            PriceSnapshot.trend.is_not(None),
            PriceSnapshot.date > start,
            PriceSnapshot.date <= end,
        )
        .order_by(PriceSnapshot.date)
    )
    changes: dict[date, list[tuple[tuple[int, str], Decimal]]] = {}
    for day, pid, finish, trend, source in snapshots:
        if source == source_of[pid]:
            changes.setdefault(day, []).append(((pid, finish), trend))

    history = []
    day = start
    while day <= end:
        for key, trend in changes.get(day, []):
            current[key] = trend
        total = Decimal(0)
        for item in items:
            price = item.manual_price
            if price is None:
                price = current.get((item.printing_id, item.finish))
            if price is not None:
                total += price * item.quantity
        history.append((day, total))
        day += timedelta(days=1)
    return currency, history


# Price bands of the finance page (upper bounds, in the shown currency).
PRICE_BANDS = (Decimal(1), Decimal(5), Decimal(20), Decimal(100))
# Periods the finance page compares the value with, in days.
FINANCE_PERIODS = (1, 7, 30, 90, 365)


@dataclass
class Share:
    key: str
    label: str
    value: Decimal = Decimal(0)
    quantity: int = 0


@dataclass
class Finance:
    currency: str
    value: Decimal
    quantity: int
    printings: int
    priced: int
    unpriced: int
    average: Decimal | None
    median: Decimal | None
    # Games left out: priced in another currency than the shown one.
    other_currencies: list[str]
    # Value then and now, by period in days (None where the history is too short).
    changes: dict[int, tuple[Decimal, Decimal] | None]
    history: list[tuple[date, Decimal]]
    by_game: list[Share]
    by_set: list[Share]
    by_rarity: list[Share]
    by_condition: list[Share]
    by_language: list[Share]
    by_finish: list[Share]
    by_band: list[Share]
    # Value of the dearest items (line value), dearest first, with the share of the
    # 10 dearest in the total.
    top: list[tuple[CollectionItem, Decimal, Decimal]]
    top_share: float | None


def _band(price: Decimal) -> int:
    return next((i for i, bound in enumerate(PRICE_BANDS) if price < bound), len(PRICE_BANDS))


def _band_label(index: int) -> str:
    if index == 0:
        return f"< {PRICE_BANDS[0]}"
    if index == len(PRICE_BANDS):
        return f"≥ {PRICE_BANDS[-1]}"
    return f"{PRICE_BANDS[index - 1]} – {PRICE_BANDS[index]}"


async def finance(
    session: AsyncSession,
    user_id: int,
    items: list[CollectionItem],
    wanted: str,
    game_id: str | None,
    today: date | None = None,
) -> Finance:
    """Market value figures of owned items (loaded with their printing and set): totals,
    change over periods, and how the value splits by game, set, rarity, condition,
    language, finish and price band. Without a game, only games priced in the user's
    source currency count (amounts in different currencies are never added up)."""
    today = today or date.today()
    currency = price_sources()[wanted].currency if wanted in price_sources() else "EUR"
    if game_id is not None and (chosen := pricing(game_id, wanted)) is not None:
        currency = chosen.currency
    others: set[str] = set()
    kept = []
    for item in items:
        game = item.printing.set.game_id
        if game_id is not None and game != game_id:
            continue
        chosen = pricing(game, wanted)
        if (chosen.currency if chosen else "EUR") != currency:
            others.add(game)
            continue
        kept.append(item)
    games = {i.printing_id: i.printing.set.game_id for i in kept}
    prices = await user_prices(session, wanted, games)

    shares: dict[str, dict[str, Share]] = {
        k: {} for k in ("game", "set", "rarity", "condition", "language", "finish", "band")
    }

    def count(kind: str, key: str, label: str, value: Decimal | None, quantity: int) -> None:
        share = shares[kind].setdefault(key, Share(key, label))
        share.quantity += quantity
        if value is not None:
            share.value += value

    total, priced, unpriced = Decimal(0), 0, 0
    units: list[tuple[Decimal, int]] = []
    lines: list[tuple[CollectionItem, Decimal, Decimal]] = []
    for item in kept:
        printing, card_set = item.printing, item.printing.set
        unit = unit_price(item, prices)
        line = unit * item.quantity if unit is not None else None
        if unit is None:
            unpriced += item.quantity
        else:
            priced += item.quantity
            total += line
            units.append((unit, item.quantity))
            lines.append((item, unit, line))
            band = _band(unit)
            count("band", str(band), _band_label(band), line, item.quantity)
        count("game", card_set.game_id, card_set.game_id, line, item.quantity)
        count("set", str(card_set.id), f"{card_set.code} · {card_set.name}", line, item.quantity)
        if printing.rarity:
            # Rarity names only compare within a game.
            key = f"{card_set.game_id}:{printing.rarity}"
            label = printing.rarity if game_id else f"{card_set.game_id} · {printing.rarity}"
            count("rarity", key, label, line, item.quantity)
        count("condition", item.condition, item.condition, line, item.quantity)
        count("language", item.language, item.language, line, item.quantity)
        count("finish", item.finish, item.finish, line, item.quantity)

    median = None
    if units:
        units.sort(key=lambda u: u[0])
        middle, seen = (priced + 1) / 2, 0
        for unit, quantity in units:
            seen += quantity
            if seen >= middle:
                median = unit
                break

    start = today - timedelta(days=max(FINANCE_PERIODS))
    _, history = await value_history(session, user_id, wanted, game_id, start, today)
    by_day = dict(history)
    # Days before the first known price count as no history (a value of 0 there means
    # nothing was priced yet).
    first = next((day for day, value in history if value), None)
    changes: dict[int, tuple[Decimal, Decimal] | None] = {}
    for days in FINANCE_PERIODS:
        day = today - timedelta(days=days)
        past = by_day.get(day)
        changes[days] = (past, total) if past is not None and first and day >= first else None

    lines.sort(key=lambda line: -line[2])
    top_share = float(sum(line[2] for line in lines[:10]) / total) if total else None

    def ordered(kind: str) -> list[Share]:
        return sorted(shares[kind].values(), key=lambda s: (-s.value, -s.quantity, s.label))

    return Finance(
        currency=currency,
        value=total,
        quantity=priced + unpriced,
        printings=len({i.printing_id for i in kept}),
        priced=priced,
        unpriced=unpriced,
        average=round(total / priced, 2) if priced else None,
        median=median,
        other_currencies=sorted(others),
        changes=changes,
        history=history,
        by_game=ordered("game"),
        by_set=ordered("set"),
        by_rarity=ordered("rarity"),
        by_condition=ordered("condition"),
        by_language=ordered("language"),
        by_finish=ordered("finish"),
        by_band=sorted(shares["band"].values(), key=lambda s: int(s.key)),
        top=lines[:10],
        top_share=top_share,
    )
