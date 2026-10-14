"""Progress of the running background job, reported from the services it calls.

Kept apart from `jobs` so services can report progress without importing the job runner.
"""

import contextvars
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import update

from app.core.db import get_sessionmaker
from app.models import SyncRun

# Heartbeats are written at most this often.
HEARTBEAT_EVERY = 30.0


@dataclass
class Progress:
    run_id: int
    last: float = field(default_factory=time.monotonic)
    written: float = 0.0


current: contextvars.ContextVar[Progress | None] = contextvars.ContextVar(
    "job_progress", default=None
)


async def progress() -> None:
    """Record that the running job made progress (a batch stored, an image downloaded).
    No-op outside jobs."""
    state = current.get()
    if state is None:
        return
    now = time.monotonic()
    state.last = now
    if now - state.written >= HEARTBEAT_EVERY:
        state.written = now
        async with get_sessionmaker()() as session:
            await session.execute(
                update(SyncRun)
                .where(SyncRun.id == state.run_id)
                .values(heartbeat_at=datetime.now(UTC))
            )
            await session.commit()
