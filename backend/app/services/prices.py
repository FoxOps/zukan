"""Price snapshots from game providers and price sources (`app.prices`).

One snapshot per printing, finish, day and source. Full history is kept for printings
someone has in a collection; for the rest only the latest snapshot survives, which is
enough to show current prices without growing the table by the whole catalog each day.
"""

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import httpx
from sqlalchemy import delete, exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.progress import progress
from app.games.base import GameProvider, PriceQuote, PriceTarget
from app.models import CardSet, CollectionItem, Game, PriceSnapshot, Printing
from app.prices.base import MarketTarget, fetches, price_sources

log = logging.getLogger(__name__)

_CHUNK = 1000


@dataclass
class PriceReport:
    # Owned printings asked for (sources priced one by one only fetch these).
    targets: int = 0
    quotes: int = 0
    stored: int = 0
    # Quotes not stored: printing missing from the catalog, no price, or duplicates.
    skipped: int = 0
    pruned: int = 0


def today() -> date:
    return datetime.now(UTC).date()


PrintingIds = dict[tuple[str, str], int]


async def printing_ids(session: AsyncSession, game_id: str) -> PrintingIds:
    """Map (set external id, printing external id) to printing id for a whole game."""
    rows = await session.execute(
        select(Printing.id, CardSet.external_id, Printing.external_id)
        .join(CardSet, Printing.set_id == CardSet.id)
        .where(CardSet.game_id == game_id)
    )
    return {(set_ext, printing_ext): pid for pid, set_ext, printing_ext in rows}


async def store_quotes(
    session: AsyncSession, quotes: Sequence[PriceQuote], day: date, ids: PrintingIds
) -> int:
    """Upsert quotes as snapshots for `day`, under each quote's source. Quotes for
    printings missing from `ids` are skipped."""
    unique: dict[tuple[str, str, str, str], PriceQuote] = {}
    for quote in quotes:
        if quote.trend is None and quote.low is None and quote.avg is None:
            continue
        key = (quote.set_external_id, quote.printing_external_id, quote.finish, quote.source)
        unique.setdefault(key, quote)
    items = list(unique.items())
    stored = 0
    for start in range(0, len(items), _CHUNK):
        chunk = items[start : start + _CHUNK]
        values = [
            {
                "printing_id": ids[(set_ext, printing_ext)],
                "finish": finish,
                "date": day,
                "source": source,
                "currency": quote.currency,
                "trend": quote.trend,
                "low": quote.low,
                "avg": quote.avg,
            }
            for (set_ext, printing_ext, finish, source), quote in chunk
            if (set_ext, printing_ext) in ids
        ]
        if not values:
            continue
        stmt = insert(PriceSnapshot).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                PriceSnapshot.printing_id,
                PriceSnapshot.finish,
                PriceSnapshot.date,
                PriceSnapshot.source,
            ],
            set_={col: stmt.excluded[col] for col in ("currency", "trend", "low", "avg")},
        )
        await session.execute(stmt)
        stored += len(values)
    return stored


async def prune_history(session: AsyncSession, game_id: str) -> int:
    """Drop superseded snapshots of printings that are in nobody's collection."""
    newer = aliased(PriceSnapshot)
    result = await session.execute(
        delete(PriceSnapshot).where(
            PriceSnapshot.printing_id.in_(
                select(Printing.id).join(CardSet).where(CardSet.game_id == game_id)
            ),
            ~exists().where(CollectionItem.printing_id == PriceSnapshot.printing_id),
            exists().where(
                newer.printing_id == PriceSnapshot.printing_id,
                newer.finish == PriceSnapshot.finish,
                newer.source == PriceSnapshot.source,
                newer.date > PriceSnapshot.date,
            ),
        )
    )
    return result.rowcount


async def owned_targets(session: AsyncSession, game_id: str) -> list[PriceTarget]:
    rows = await session.execute(
        select(CardSet.external_id, Printing.external_id, CardSet.lang)
        .distinct()
        .join(Printing, Printing.set_id == CardSet.id)
        .join(CollectionItem, CollectionItem.printing_id == Printing.id)
        .where(CardSet.game_id == game_id, CollectionItem.quantity > 0)
        .order_by(CardSet.external_id, Printing.external_id)
    )
    return [PriceTarget(*row) for row in rows]


async def market_targets(session: AsyncSession, game_id: str) -> list[MarketTarget]:
    """Every printing of the game, for sources fetching prices with their own API."""
    rows = await session.execute(
        select(CardSet.external_id, Printing.external_id, Printing.finishes, Printing.attributes)
        .join(Printing, Printing.set_id == CardSet.id)
        .where(CardSet.game_id == game_id)
    )
    return [
        MarketTarget(set_ext, printing_ext, tuple(finishes), dict(attrs.get("market_ids") or {}))
        for set_ext, printing_ext, finishes, attrs in rows
    ]


async def sync_prices(
    session: AsyncSession, provider: GameProvider, http: httpx.AsyncClient
) -> PriceReport:
    """Prices from the game's own data, then from sources with their own API."""
    report = PriceReport()
    ids = await printing_ids(session, provider.id)
    day = today()

    async def store(batches: AsyncIterator[list[PriceQuote]]) -> None:
        async for quotes in batches:
            report.quotes += len(quotes)
            stored = await store_quotes(session, quotes, day, ids)
            report.stored += stored
            report.skipped += len(quotes) - stored
            await session.commit()
            await progress()

    if provider.price_sources:
        targets = await owned_targets(session, provider.id)
        report.targets = len(targets)
        await store(provider.fetch_prices(http, targets))
    standalone = [s for s in price_sources().values() if fetches(s, provider.id)]
    if standalone:
        everything = await market_targets(session, provider.id)
        for source in standalone:
            fetch: Any = source.fetch
            try:
                await store(fetch(http, provider.id, everything))
            except httpx.HTTPError as exc:
                # One market down does not cost the others their prices.
                log.warning("%s prices for %s unavailable: %s", source.id, provider.id, exc)
    report.pruned = await prune_history(session, provider.id)
    await session.execute(
        update(Game).where(Game.id == provider.id).values(last_price_sync=datetime.now(UTC))
    )
    await session.commit()
    return report


def has_prices(provider: GameProvider) -> bool:
    return bool(provider.price_sources) or any(
        fetches(s, provider.id) for s in price_sources().values()
    )
