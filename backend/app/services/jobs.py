"""Background jobs (catalog sync, prices, images) with run history.

A partial unique index on `sync_run` guarantees one running job per game and kind,
whether started by the worker, the CLI or an admin from the web UI.

Jobs report progress through `progress.progress()` (a batch stored, an image downloaded). A job
without progress for `STALL_AFTER`, or running longer than its kind's time limit, is
stopped and recorded as failed. Runs left behind by a process that stopped are failed
when that process starts again, or by any process once their heartbeat is too old.

The worker's runs are `auto`, the others `manual`. A manual run takes over a running auto
run of the same game and kind: the auto run is asked to stop (its owner checks every few
seconds) and the manual one starts.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import false, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.http import http_client
from app.core.progress import Progress, current
from app.games.base import get_provider
from app.models import JobKind, JobStatus, JobTrigger, SyncRun
from app.services import images, prices, refresh
from app.services.catalog import sync_catalog

log = logging.getLogger(__name__)

# A job without progress for this long is stuck (hung connection, endless retry...).
STALL_AFTER = timedelta(minutes=15)
# Longest run per kind; MTG catalogs take ~10 minutes, Pokémon ones with every Asian
# language about an hour.
TIME_LIMITS = {
    JobKind.catalog: timedelta(hours=6),
    JobKind.prices: timedelta(hours=2),
    JobKind.images: timedelta(hours=6),
    JobKind.refresh: timedelta(hours=2),
}
# How often the owner of a job checks for a cancel request and its own limits.
CHECK_EVERY = 5.0
# How long a manual run waits for the auto run it takes over to stop.
TAKEOVER_WAIT = 60.0

# This process ("api", "worker" or "cli", set by its entry point) and its instance.
INSTANCE = uuid.uuid4().hex[:12]
_role = "api"


def set_process_role(role: str) -> None:
    global _role
    _role = role


def owner() -> str:
    return f"{_role}:{INSTANCE}"


class JobAlreadyRunning(Exception):
    pass


class JobStopped(Exception):
    """The job was stopped: stalled, too long, or cancelled by a manual run."""

    def __init__(self, status: JobStatus, reason: str) -> None:
        super().__init__(reason)
        self.status = status


async def _set(run_id: int, **values) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(update(SyncRun).where(SyncRun.id == run_id).values(**values))
        await session.commit()


async def reap_runs() -> int:
    """Fail running jobs whose process is gone: left behind by an earlier instance of this
    process, or without heartbeat for longer than a stall (any process)."""
    now = datetime.now(UTC)
    dead = now - STALL_AFTER - timedelta(minutes=5)
    async with get_sessionmaker()() as session:
        result = await session.execute(
            update(SyncRun)
            .where(
                SyncRun.status == JobStatus.running,
                or_(
                    # Several command line runs may go on at once: only the long-lived
                    # processes know that their earlier instance is gone.
                    (SyncRun.owner.like(f"{_role}:%") & (SyncRun.owner != owner()))
                    if _role != "cli"
                    else false(),
                    SyncRun.heartbeat_at < dead,
                    SyncRun.heartbeat_at.is_(None) & (SyncRun.started_at < dead),
                ),
            )
            .values(
                status=JobStatus.failed,
                error="Interrupted: the process running it stopped",
                finished_at=now,
            )
        )
        await session.commit()
    if result.rowcount:
        log.warning("Marked %s interrupted job(s) as failed", result.rowcount)
    return result.rowcount


async def _insert(game_id: str, kind: JobKind, trigger: JobTrigger) -> int:
    async with get_sessionmaker()() as session:
        now = datetime.now(UTC)
        run = SyncRun(game_id=game_id, kind=kind, trigger=trigger, owner=owner(), heartbeat_at=now)
        session.add(run)
        await session.commit()
        return run.id


async def _running(game_id: str, kind: JobKind) -> SyncRun | None:
    async with get_sessionmaker()() as session:
        return await session.scalar(
            select(SyncRun).where(
                SyncRun.game_id == game_id,
                SyncRun.kind == kind,
                SyncRun.status == JobStatus.running,
            )
        )


async def _take_over(run: SyncRun) -> None:
    """Stop a running auto run so a manual one can start."""
    await _set(run.id, cancel_requested=True)
    deadline = time.monotonic() + TAKEOVER_WAIT
    while time.monotonic() < deadline:
        await asyncio.sleep(1)
        current = await _running(run.game_id, run.kind)
        if current is None or current.id != run.id:
            return
    # The owner did not answer: record it as cancelled anyway.
    async with get_sessionmaker()() as session:
        await session.execute(
            update(SyncRun)
            .where(SyncRun.id == run.id, SyncRun.status == JobStatus.running)
            .values(
                status=JobStatus.cancelled,
                error="Cancelled by a manual run",
                finished_at=datetime.now(UTC),
            )
        )
        await session.commit()


async def start_job(game_id: str, kind: JobKind, trigger: JobTrigger = JobTrigger.manual) -> int:
    """Record a running job. Raises JobAlreadyRunning when the same game and kind runs
    already (for a manual run: another manual run)."""
    get_provider(game_id)  # fail fast on unknown game
    await reap_runs()
    for _ in range(2):
        try:
            return await _insert(game_id, kind, trigger)
        except IntegrityError:
            running = await _running(game_id, kind)
            if running is None:
                continue  # finished meanwhile
            if trigger == JobTrigger.auto or running.trigger == JobTrigger.manual:
                break
            log.info("Manual %s job for %s takes over run %s", kind, game_id, running.id)
            await _take_over(running)
    raise JobAlreadyRunning(f"{kind} job for {game_id} is already running")


async def _finish(run_id: int, status: JobStatus, report: dict, error: str | None) -> None:
    async with get_sessionmaker()() as session:
        # A run already failed by a watchdog or cancelled keeps that outcome.
        await session.execute(
            update(SyncRun)
            .where(SyncRun.id == run_id, SyncRun.status == JobStatus.running)
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
            case JobKind.refresh:
                every = timedelta(hours=get_settings().refresh_interval_hours)
                return asdict(await refresh.refresh_stale(session, provider, http, every))


async def _stop_reason(run_id: int, state: Progress, started: float, limit: timedelta):
    now = time.monotonic()
    if now - started > limit.total_seconds():
        hours = limit.total_seconds() / 3600
        return JobStopped(JobStatus.failed, f"Timed out after {hours:g} h")
    if now - state.last > STALL_AFTER.total_seconds():
        minutes = STALL_AFTER.total_seconds() / 60
        return JobStopped(JobStatus.failed, f"Stuck: no progress for {minutes:g} min")
    async with get_sessionmaker()() as session:
        row = (
            await session.execute(
                select(SyncRun.status, SyncRun.cancel_requested).where(SyncRun.id == run_id)
            )
        ).one_or_none()
    if row is None or row.status != JobStatus.running:
        return JobStopped(JobStatus.failed, "Stopped elsewhere")
    if row.cancel_requested:
        return JobStopped(JobStatus.cancelled, "Cancelled by a manual run")
    return None


async def _supervised(run_id: int, game_id: str, kind: JobKind) -> dict:
    """Run the job, stopping it when it stalls, exceeds its time limit or is cancelled."""
    state = Progress(run_id)
    token = current.set(state)
    try:
        task = asyncio.create_task(_execute(game_id, kind))
    finally:
        current.reset(token)
    started = time.monotonic()
    limit = TIME_LIMITS.get(kind, timedelta(hours=2))
    while True:
        done, _ = await asyncio.wait({task}, timeout=CHECK_EVERY)
        if done:
            return task.result()
        stop = await _stop_reason(run_id, state, started, limit)
        if stop is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise stop


async def complete_job(run_id: int, game_id: str, kind: JobKind) -> None:
    """Execute a job recorded by `start_job` and store its outcome."""
    log.info("Starting %s job for %s (run %s)", kind, game_id, run_id)
    try:
        report = await _supervised(run_id, game_id, kind)
    except JobStopped as exc:
        log.warning("%s job for %s stopped: %s", kind, game_id, exc)
        await _finish(run_id, exc.status, {}, str(exc))
        raise
    except Exception as exc:
        log.exception("%s job for %s failed", kind, game_id)
        await _finish(run_id, JobStatus.failed, {}, f"{type(exc).__name__}: {exc}"[:2000])
        raise
    await _finish(run_id, JobStatus.success, report, None)
    log.info("Finished %s job for %s: %s", kind, game_id, report)


async def run_job(game_id: str, kind: JobKind, trigger: JobTrigger = JobTrigger.manual) -> int:
    """Run a job to completion and return its run id."""
    run_id = await start_job(game_id, kind, trigger)
    await complete_job(run_id, game_id, kind)
    return run_id
