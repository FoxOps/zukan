"""Background worker: keeps catalogs, prices and images fresh.

Wakes every few minutes and runs each job whose last success is older than
`TCG_CATALOG_INTERVAL_HOURS` (catalogs) or `TCG_SYNC_INTERVAL_HOURS` (prices, images).
Failed jobs are retried after `RETRY_AFTER`.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.games.base import registry
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


def interval(kind: JobKind) -> timedelta:
    settings = get_settings()
    if kind == JobKind.catalog:
        return timedelta(hours=settings.catalog_interval_hours)
    return timedelta(hours=settings.sync_interval_hours)


async def is_due(game_id: str, kind: JobKind, now: datetime) -> bool:
    last_success = await _last(game_id, kind, JobStatus.success)
    if last_success is not None and now - last_success < interval(kind):
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
