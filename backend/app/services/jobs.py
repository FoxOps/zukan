"""Background jobs (catalog sync, prices, images) with run history.

A partial unique index on `sync_run` guarantees one running job per game and kind,
whether started by the worker, the CLI or an admin from the web UI.
"""

import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.core.db import get_sessionmaker
from app.core.http import http_client
from app.games.base import get_provider
from app.models import JobKind, JobStatus, SyncRun
from app.services import images, prices
from app.services.catalog import sync_catalog

log = logging.getLogger(__name__)

# A job still "running" after this long is assumed dead (process killed).
STALE_AFTER = timedelta(hours=6)


class JobAlreadyRunning(Exception):
    pass


async def start_job(game_id: str, kind: JobKind) -> int:
    """Record a running job. Raises JobAlreadyRunning."""
    get_provider(game_id)  # fail fast on unknown game
    async with get_sessionmaker()() as session:
        await session.execute(
            update(SyncRun)
            .where(
                SyncRun.game_id == game_id,
                SyncRun.kind == kind,
                SyncRun.status == JobStatus.running,
                SyncRun.started_at < datetime.now(UTC) - STALE_AFTER,
            )
            .values(status=JobStatus.failed, error="Interrupted", finished_at=datetime.now(UTC))
        )
        run = SyncRun(game_id=game_id, kind=kind)
        session.add(run)
        try:
            await session.commit()
        except IntegrityError as exc:
            raise JobAlreadyRunning(f"{kind} job for {game_id} is already running") from exc
        return run.id


async def _finish(run_id: int, status: JobStatus, report: dict, error: str | None) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(
            update(SyncRun)
            .where(SyncRun.id == run_id)
            .values(status=status, report=report, error=error, finished_at=datetime.now(UTC))
        )
        await session.commit()


async def _execute(game_id: str, kind: JobKind) -> dict:
    provider = get_provider(game_id)
    async with get_sessionmaker()() as session, http_client() as http:
        match kind:
            case JobKind.catalog:
                return asdict(await sync_catalog(session, provider, http))
            case JobKind.images:
                return asdict(await images.cache_images(session, http, game_id))
            case JobKind.prices:
                return asdict(await prices.sync_prices(session, provider, http))


async def complete_job(run_id: int, game_id: str, kind: JobKind) -> None:
    """Execute a job recorded by `start_job` and store its outcome."""
    log.info("Starting %s job for %s (run %s)", kind, game_id, run_id)
    try:
        report = await _execute(game_id, kind)
    except Exception as exc:
        log.exception("%s job for %s failed", kind, game_id)
        await _finish(run_id, JobStatus.failed, {}, f"{type(exc).__name__}: {exc}"[:2000])
        raise
    await _finish(run_id, JobStatus.success, report, None)
    log.info("Finished %s job for %s: %s", kind, game_id, report)


async def run_job(game_id: str, kind: JobKind) -> int:
    """Run a job to completion and return its run id."""
    run_id = await start_job(game_id, kind)
    await complete_job(run_id, game_id, kind)
    return run_id
