"""Stale cards and their refresh from the game's source (internal, not shown in the UI).

A card is stale when:
- the last successful catalog sync of its game did not see it (`last_seen_at` older than
  that sync's start), once that sync finished more than `STALE_GRACE` ago;
- or its data is incomplete: no printing has an image source, or no card attributes.

Stale cards are refreshed one by one when someone opens them, and in bulk by the refresh
job (`TCG_REFRESH_INTERVAL_HOURS`). Each card is retried at most once per
`RETRY_AFTER` (on view) or per refresh interval (job), so cards a source never
completes do not cost a request on every view.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import ColumnElement, and_, exists, false, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.progress import progress
from app.games.base import CardRef, GameProvider, PrintingRef
from app.models import Card, JobKind, JobStatus, Printing, SyncRun
from app.services.catalog import CatalogWriter

log = logging.getLogger(__name__)

STALE_GRACE = timedelta(hours=24)
# On view, a stale card is fetched again at most this often.
RETRY_AFTER = timedelta(hours=1)
# Cards per `fetch_cards` call in the refresh job.
CHUNK = 200


@dataclass
class RefreshReport:
    checked: int = 0
    updated: int = 0
    not_found: int = 0


def can_refresh(provider: GameProvider) -> bool:
    return hasattr(provider, "fetch_cards")


async def last_full_sync(session: AsyncSession, game_id: str) -> SyncRun | None:
    return await session.scalar(
        select(SyncRun)
        .where(
            SyncRun.game_id == game_id,
            SyncRun.kind == JobKind.catalog,
            SyncRun.status == JobStatus.success,
        )
        .order_by(SyncRun.started_at.desc())
        .limit(1)
    )


def _has_image() -> ColumnElement[bool]:
    return exists().where(
        Printing.card_id == Card.id,
        or_(
            Printing.image_urls != text("'{}'::jsonb"),
            func.jsonb_path_exists(Printing.image_paths, text("'$.* ? (@ != \"\")'")),
        ),
    )


async def stale_condition(
    session: AsyncSession, game_id: str, now: datetime | None = None
) -> ColumnElement[bool]:
    """SQL condition on `Card` matching the game's stale cards."""
    now = now or datetime.now(UTC)
    sync = await last_full_sync(session, game_id)
    missed: ColumnElement[bool] = false()
    if sync is not None and sync.finished_at and now > sync.finished_at + STALE_GRACE:
        missed = Card.last_seen_at < sync.started_at
    return and_(
        Card.game_id == game_id,
        or_(missed, ~_has_image(), Card.attributes == text("'{}'::jsonb")),
    )


async def is_stale(session: AsyncSession, card: Card) -> bool:
    condition = await stale_condition(session, card.game_id)
    return bool(await session.scalar(select(exists().where(Card.id == card.id, condition))))


def card_ref(card: Card) -> CardRef:
    return CardRef(
        external_id=card.external_id,
        name=card.name,
        printings=tuple(
            PrintingRef(
                set_external_id=p.set.external_id,
                external_id=p.external_id,
                set_lang=p.set.lang,
                languages=tuple(p.languages),
                image_languages=tuple(p.image_urls),
                attributes=dict(p.attributes),
            )
            for p in card.printings
        ),
    )


async def refresh_cards(
    session: AsyncSession, provider: GameProvider, http: httpx.AsyncClient, card_ids: list[int]
) -> RefreshReport:
    """Fetch these cards again from the provider and store what comes back."""
    report = RefreshReport(checked=len(card_ids))
    if not card_ids or not can_refresh(provider):
        return report
    cards = (
        await session.scalars(
            select(Card)
            .where(Card.id.in_(card_ids), Card.game_id == provider.id)
            .options(selectinload(Card.printings).selectinload(Printing.set))
        )
    ).all()
    refs = [card_ref(card) for card in cards]
    await session.execute(
        update(Card)
        .where(Card.id.in_([c.id for c in cards]))
        .values(refresh_attempted_at=datetime.now(UTC))
    )
    await session.commit()

    wanted = {ref.external_id for ref in refs}
    found: set[str] = set()
    writer = CatalogWriter(session, provider.id)
    await writer.load_sets()
    fetch: Any = provider.fetch_cards
    async for batch in fetch(http, refs):
        await writer.write(batch)
        await session.commit()
        await progress()
        found |= {card.external_id for card in batch.cards} & wanted
    report.updated = len(found)
    report.not_found = len(wanted - found)
    if report.not_found:
        log.info("%s %s cards not found at the source", report.not_found, provider.id)
    return report


async def refresh_stale(
    session: AsyncSession, provider: GameProvider, http: httpx.AsyncClient, every: timedelta
) -> RefreshReport:
    """Refresh the game's stale cards not tried within `every`."""
    report = RefreshReport()
    if not can_refresh(provider):
        return report
    condition = await stale_condition(session, provider.id)
    tried_before = datetime.now(UTC) - every
    ids = list(
        await session.scalars(
            select(Card.id)
            .where(
                condition,
                or_(Card.refresh_attempted_at.is_(None), Card.refresh_attempted_at < tried_before),
            )
            .order_by(Card.id)
        )
    )
    for start in range(0, len(ids), CHUNK):
        part = await refresh_cards(session, provider, http, ids[start : start + CHUNK])
        report.checked += part.checked
        report.updated += part.updated
        report.not_found += part.not_found
    return report
