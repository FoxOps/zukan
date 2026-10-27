"""Maintenance mode while a catalog refresh slows the server down.

A catalog refresh (run by the worker) downloads and stores hundreds of thousands of
printings: on a small machine it competes with users' requests for the CPU and the
database. The API process measures its own responsiveness every `SAMPLE_SECONDS`:

- a probe: event loop delay plus a database round trip,
- the time of the API requests answered since the previous sample.

When the median of the last `WINDOW` samples exceeds `TCG_MAINTENANCE_LATENCY_MS` while a
catalog job runs, the server enters maintenance: users get a maintenance page (and 503 on
the API), administrators keep access to watch or cancel the job. It leaves maintenance
after `CALM` samples in a row under the limit, or as soon as no catalog job runs.
"""

import asyncio
import logging
import statistics
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models import JobKind, JobStatus, SyncRun

log = logging.getLogger(__name__)

SAMPLE_SECONDS = 2.0
# Samples making the slow window (20 s), and fast samples in a row needed to leave (30 s).
WINDOW = 10
CALM = 15


@dataclass(frozen=True)
class Maintenance:
    since: datetime
    # Game whose catalog refresh is running.
    game_id: str


class LoadMonitor:
    """Maintenance state from latency samples (milliseconds)."""

    def __init__(self, limit_ms: float) -> None:
        self.limit_ms = limit_ms
        self.samples: deque[float] = deque(maxlen=WINDOW)
        self.calm = 0
        self.state: Maintenance | None = None

    def _reset(self) -> None:
        self.samples.clear()
        self.calm = 0
        self.state = None

    def record(self, latency_ms: float, catalog_game: str | None, now: datetime) -> None:
        if catalog_game is None:
            if self.state is not None:
                log.info("Maintenance ends: no catalog refresh running")
            self._reset()
            return
        self.samples.append(latency_ms)
        if self.state is None:
            full = len(self.samples) == WINDOW
            if full and statistics.median(self.samples) > self.limit_ms:
                self.state = Maintenance(since=now, game_id=catalog_game)
                self.calm = 0
                log.warning(
                    "Maintenance starts: %s catalog refresh slows the server (median %.0f ms)",
                    catalog_game,
                    statistics.median(self.samples),
                )
            return
        self.calm = self.calm + 1 if latency_ms <= self.limit_ms else 0
        if self.calm >= CALM:
            log.info("Maintenance ends: the server is fast again")
            self._reset()


_monitor: LoadMonitor | None = None
# Durations (ms) of the API requests answered since the last sample.
_requests: list[float] = []


def maintenance() -> Maintenance | None:
    return _monitor.state if _monitor is not None else None


def record_request(duration_ms: float) -> None:
    if _monitor is not None and len(_requests) < 1000:
        _requests.append(duration_ms)


async def _catalog_game() -> str | None:
    async with get_sessionmaker()() as session:
        return await session.scalar(
            select(SyncRun.game_id)
            .where(SyncRun.kind == JobKind.catalog, SyncRun.status == JobStatus.running)
            .limit(1)
        )


async def _sample(loop_delay_ms: float) -> tuple[float, str | None]:
    """Latency (ms) and the game whose catalog refresh runs, if any."""
    start = time.perf_counter()
    game_id = await _catalog_game()
    probe = loop_delay_ms + (time.perf_counter() - start) * 1000
    answered = _requests[:]
    _requests.clear()
    return max(probe, statistics.median(answered)) if answered else probe, game_id


async def watch() -> None:
    """Sample forever (API process lifespan task)."""
    global _monitor
    settings = get_settings()
    if not settings.maintenance_enabled:
        return
    _monitor = LoadMonitor(settings.maintenance_latency_ms)
    while True:
        start = time.perf_counter()
        await asyncio.sleep(SAMPLE_SECONDS)
        # Event loop delay: how late this task wakes up.
        delay = max(0.0, (time.perf_counter() - start - SAMPLE_SECONDS) * 1000)
        try:
            latency, game_id = await _sample(delay)
        except Exception:
            log.exception("Load sample failed")
            continue
        _monitor.record(latency, game_id, datetime.now(UTC))
