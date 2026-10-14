"""Background worker: keeps catalogs, prices and images fresh.

Wakes every few minutes and runs each job whose last success is older than
`TCG_CATALOG_INTERVAL_HOURS` (catalogs) or `TCG_SYNC_INTERVAL_HOURS` (prices, images).
Failed jobs are retried after `RETRY_AFTER`. A catalog is also due when its provider's
`catalog_version` is newer than the one of the last successful sync (after an upgrade),
and images when the catalog changed since the last image run (new image URLs).
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.games.base import catalog_version, registry
from app.main import register_games
from app.models import JobKind, JobStatus, SyncRun
from app.services.jobs import JobAlreadyRunning, run_job

log = logging.getLogger("fudabako.worker")

TICK_SECONDS = 300
RETRY_AFTER = timedelta(hours=1)


async def _last(game_id: str, kind: JobKind, status: JobStatus | None) -> datetime | None:
    query = select(func.max(SyncRun.started_at)).where(
        SyncRun.game_id == game_id, SyncRun.kind == kind
    )
    if status is not None:
        query = query.where(SyncRun.status == status)
    async with get_sessionmaker()() as session:
        return await session.scalar(query)


async def _last_success(game_id: str, kind: JobKind) -> SyncRun | None:
    async with get_sessionmaker()() as session:
        return await session.scalar(
            select(SyncRun)
            .where(
                SyncRun.game_id == game_id,
                SyncRun.kind == kind,
                SyncRun.status == JobStatus.success,
            )
            .order_by(SyncRun.started_at.desc())
            .limit(1)
        )


async def _outdated(game_id: str, kind: JobKind, last_success: SyncRun) -> bool:
    """Stored data older than the code (catalog) or than the catalog (images)."""
    if kind == JobKind.catalog:
        stored = (last_success.report or {}).get("catalog_version", 1)
        return stored < catalog_version(registry()[game_id])
    if kind == JobKind.images:
        catalog = await _last_success(game_id, JobKind.catalog)
        return catalog is not None and catalog.started_at > last_success.started_at
    return False


def interval(kind: JobKind) -> timedelta:
    settings = get_settings()
    if kind == JobKind.catalog:
        return timedelta(hours=settings.catalog_interval_hours)
    return timedelta(hours=settings.sync_interval_hours)


async def is_due(game_id: str, kind: JobKind, now: datetime) -> bool:
    last_success = await _last_success(game_id, kind)
    if (
        last_success is not None
        and now - last_success.started_at < interval(kind)
        and not await _outdated(game_id, kind, last_success)
    ):
        return False
    last_attempt = await _last(game_id, kind, None)
    return last_attempt is None or now - last_attempt >= RETRY_AFTER


def jobs_for(game_id: str) -> list[JobKind]:
    kinds = [JobKind.catalog]
    if registry()[game_id].price_source is not None:
        kinds.append(JobKind.prices)
    kinds.append(JobKind.images)
    return kinds


async def tick() -> None:
    games = get_settings().worker_games or list(registry())
    for game_id in games:
        for kind in jobs_for(game_id):
            if not await is_due(game_id, kind, datetime.now(UTC)):
                continue
            try:
                await run_job(game_id, kind)
            except JobAlreadyRunning:
                log.info("%s/%s already running elsewhere", game_id, kind)
            except Exception:
                # Logged and recorded in sync_run; later jobs of this game still run.
                pass


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    await register_games()
    while True:
        await tick()
        await asyncio.sleep(TICK_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
