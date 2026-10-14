"""Background worker: keeps catalogs, prices and images fresh.

Wakes every few minutes and runs each job whose last success is older than
`TCG_CATALOG_INTERVAL_HOURS` (catalogs) or `TCG_SYNC_INTERVAL_HOURS` (prices, images).
Failed jobs are retried after `RETRY_AFTER`. A catalog is also due when its provider's
`catalog_version` is newer than the one of the last successful sync (after an upgrade),
and images when the catalog changed since the last image run (new image URLs).

The schedule only follows the worker's own (`auto`) runs: manual runs neither delay nor
replace them.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.games.base import catalog_version, registry
from app.main import register_games
from app.models import JobKind, JobStatus, JobTrigger, SyncRun
from app.services.jobs import JobAlreadyRunning, JobStopped, reap_runs, run_job, set_process_role
from app.services.prices import has_prices
from app.services.refresh import can_refresh

log = logging.getLogger("fudabako.worker")

TICK_SECONDS = 300
RETRY_AFTER = timedelta(hours=1)


async def _last_attempt(game_id: str, kind: JobKind) -> datetime | None:
    """Start of the last auto run that did not end cancelled (a cancelled run is retried
    at once)."""
    query = select(func.max(SyncRun.started_at)).where(
        SyncRun.game_id == game_id,
        SyncRun.kind == kind,
        SyncRun.trigger == JobTrigger.auto,
        SyncRun.status != JobStatus.cancelled,
    )
    async with get_sessionmaker()() as session:
        return await session.scalar(query)


async def _last_success(game_id: str, kind: JobKind, auto_only: bool = True) -> SyncRun | None:
    query = select(SyncRun).where(
        SyncRun.game_id == game_id,
        SyncRun.kind == kind,
        SyncRun.status == JobStatus.success,
    )
    if auto_only:
        query = query.where(SyncRun.trigger == JobTrigger.auto)
    async with get_sessionmaker()() as session:
        return await session.scalar(query.order_by(SyncRun.started_at.desc()).limit(1))


async def _outdated(game_id: str, kind: JobKind, last_success: SyncRun) -> bool:
    """Stored data older than the code (catalog) or than the catalog (images). Manual runs
    count here: the data they stored is what is checked."""
    if kind == JobKind.catalog:
        latest = await _last_success(game_id, kind, auto_only=False) or last_success
        stored = (latest.report or {}).get("catalog_version", 1)
        return stored < catalog_version(registry()[game_id])
    if kind == JobKind.images:
        catalog = await _last_success(game_id, JobKind.catalog, auto_only=False)
        images = await _last_success(game_id, kind, auto_only=False) or last_success
        return catalog is not None and catalog.started_at > images.started_at
    return False


def interval(kind: JobKind) -> timedelta:
    settings = get_settings()
    if kind == JobKind.catalog:
        return timedelta(hours=settings.catalog_interval_hours)
    if kind == JobKind.refresh:
        return timedelta(hours=settings.refresh_interval_hours)
    return timedelta(hours=settings.sync_interval_hours)


async def is_due(game_id: str, kind: JobKind, now: datetime) -> bool:
    last_success = await _last_success(game_id, kind)
    if (
        last_success is not None
        and now - last_success.started_at < interval(kind)
        and not await _outdated(game_id, kind, last_success)
    ):
        return False
    last_attempt = await _last_attempt(game_id, kind)
    return last_attempt is None or now - last_attempt >= RETRY_AFTER


def jobs_for(game_id: str) -> list[JobKind]:
    kinds = [JobKind.catalog]
    if has_prices(registry()[game_id]):
        kinds.append(JobKind.prices)
    kinds.append(JobKind.images)
    if can_refresh(registry()[game_id]):
        kinds.append(JobKind.refresh)
    return kinds


async def tick() -> None:
    await reap_runs()
    games = get_settings().worker_games or list(registry())
    for game_id in games:
        for kind in jobs_for(game_id):
            if not await is_due(game_id, kind, datetime.now(UTC)):
                continue
            try:
                await run_job(game_id, kind, JobTrigger.auto)
            except JobAlreadyRunning:
                log.info("%s/%s already running elsewhere", game_id, kind)
            except JobStopped:
                pass  # recorded in sync_run
            except Exception:
                # Logged and recorded in sync_run; later jobs of this game still run.
                pass


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    set_process_role("worker")
    await register_games()
    await reap_runs()
    while True:
        await tick()
        await asyncio.sleep(TICK_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
