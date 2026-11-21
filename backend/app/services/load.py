"""Maintenance mode while a catalog refresh slows the server down.

A catalog refresh (run by the worker) downloads and stores hundreds of thousands of
printings: on a small machine it competes with users' requests for the CPU and the
database. The API process measures its own responsiveness every `SAMPLE_SECONDS`:

- a probe: event loop delay plus a database round trip,
- the time of the API requests answered since the previous sample.

When the median of the last `WINDOW` samples exceeds `TCG_MAINTENANCE_LATENCY_MS` while a
catalog job runs, the server enters maintenance: users get a maintenance page (and 503 on
the API), administrators keep access to watch or cancel the job. Once in, it stays until the
data sync is over: no job (any kind, any game) running for `IDLE` samples in a row, so the
short gaps between the jobs of one worker run don't end it. Leaving as soon as the server
looked fast again made the page come and go during a sync.

Administrators can also start maintenance by hand (Admin > Server) before heavy work on the
server. That one is stored in the `maintenance` setting, so it survives restarts and every
API process reads it at each sample; it lasts until an administrator stops it and comes
before the automatic one. `TCG_MAINTENANCE_ENABLED` only turns the automatic one off.
"""

import asyncio
import logging
import statistics
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models import AppSetting, JobKind, JobStatus, SyncRun

log = logging.getLogger(__name__)

SAMPLE_SECONDS = 2.0
# Samples making the slow window (20 s), and samples in a row without any job needed to
# leave (30 s).
WINDOW = 10
IDLE = 15
# Setting holding the maintenance started by an administrator: {"since", "by"}.
SETTING_KEY = "maintenance"


@dataclass(frozen=True)
class Maintenance:
    since: datetime
    # Game whose job is running (the catalog refresh that started it, then the next ones);
    # none for a maintenance started by an administrator.
    game_id: str | None = None
    # "sync": a data sync slows the server down; "admin": started by an administrator.
    reason: Literal["sync", "admin"] = "sync"
    # Administrator who started it.
    by: str | None = None


class LoadMonitor:
    """Maintenance state from latency samples (milliseconds)."""

    def __init__(self, limit_ms: float) -> None:
        self.limit_ms = limit_ms
        self.samples: deque[float] = deque(maxlen=WINDOW)
        self.idle = 0
        self.state: Maintenance | None = None

    def _reset(self) -> None:
        self.samples.clear()
        self.idle = 0
        self.state = None

    def record(
        self, latency_ms: float, catalog_game: str | None, active_game: str | None, now: datetime
    ) -> None:
        """`catalog_game`: game whose catalog refresh runs; `active_game`: game of any job
        running (the catalog one first)."""
        if self.state is not None:
            if active_game is None:
                self.idle += 1
                if self.idle >= IDLE:
                    log.info("Maintenance ends: data sync over")
                    self._reset()
                return
            self.idle = 0
            if active_game != self.state.game_id:
                self.state = Maintenance(since=self.state.since, game_id=active_game)
            return
        if catalog_game is None:
            self.samples.clear()
            return
        self.samples.append(latency_ms)
        if len(self.samples) == WINDOW and statistics.median(self.samples) > self.limit_ms:
            self.state = Maintenance(since=now, game_id=catalog_game)
            self.idle = 0
            log.warning(
                "Maintenance starts: %s catalog refresh slows the server (median %.0f ms)",
                catalog_game,
                statistics.median(self.samples),
            )


_monitor: LoadMonitor | None = None
# Maintenance started by an administrator, as last read from the database.
_manual: Maintenance | None = None
# Durations (ms) of the API requests answered since the last sample.
_requests: list[float] = []


def maintenance() -> Maintenance | None:
    """Current maintenance: the administrator's first, else the automatic one."""
    if _manual is not None:
        return _manual
    return _monitor.state if _monitor is not None else None


async def _read_manual(session: AsyncSession) -> Maintenance | None:
    row = await session.get(AppSetting, SETTING_KEY, populate_existing=True)
    if row is None:
        return None
    return Maintenance(
        since=datetime.fromisoformat(row.value["since"]), reason="admin", by=row.value.get("by")
    )


async def load_manual() -> None:
    """Reads the administrator's maintenance (another API process may have changed it)."""
    global _manual
    async with get_sessionmaker()() as session:
        _manual = await _read_manual(session)


async def set_manual(session: AsyncSession, enabled: bool, by: str) -> Maintenance | None:
    """Starts (kept as is when already on) or stops the administrator's maintenance."""
    global _manual
    row = await session.get(AppSetting, SETTING_KEY)
    if enabled and row is None:
        now = datetime.now(UTC)
        session.add(AppSetting(key=SETTING_KEY, value={"since": now.isoformat(), "by": by}))
        log.warning("Maintenance started by %s", by)
    elif not enabled and row is not None:
        await session.delete(row)
        log.info("Maintenance ended by %s", by)
    await session.commit()
    _manual = await _read_manual(session)
    return _manual


def record_request(duration_ms: float) -> None:
    if _monitor is not None and len(_requests) < 1000:
        _requests.append(duration_ms)


@dataclass(frozen=True)
class Activity:
    # Game whose catalog refresh runs, and game of any job running (catalog first).
    catalog_game: str | None
    active_game: str | None


async def _activity() -> Activity:
    async with get_sessionmaker()() as session:
        rows = (
            await session.execute(
                select(SyncRun.game_id, SyncRun.kind).where(SyncRun.status == JobStatus.running)
            )
        ).all()
    catalog = next((game for game, kind in rows if kind == JobKind.catalog), None)
    return Activity(catalog, catalog or (rows[0][0] if rows else None))


async def _sample(loop_delay_ms: float) -> tuple[float, Activity]:
    """Latency (ms) and the jobs running."""
    start = time.perf_counter()
    activity = await _activity()
    probe = loop_delay_ms + (time.perf_counter() - start) * 1000
    answered = _requests[:]
    _requests.clear()
    return max(probe, statistics.median(answered)) if answered else probe, activity


async def watch() -> None:
    """Sample forever (API process lifespan task)."""
    global _monitor
    settings = get_settings()
    # Off: only the administrator's maintenance.
    if settings.maintenance_enabled:
        _monitor = LoadMonitor(settings.maintenance_latency_ms)
    try:
        await load_manual()
    except Exception:
        log.exception("Maintenance setting not read")
    while True:
        start = time.perf_counter()
        await asyncio.sleep(SAMPLE_SECONDS)
        # Event loop delay: how late this task wakes up.
        delay = max(0.0, (time.perf_counter() - start - SAMPLE_SECONDS) * 1000)
        try:
            await load_manual()
            if _monitor is None:
                continue
            latency, activity = await _sample(delay)
        except Exception:
            log.exception("Load sample failed")
            continue
        _monitor.record(latency, activity.catalog_game, activity.active_game, datetime.now(UTC))
