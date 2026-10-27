import enum
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class JobKind(enum.StrEnum):
    catalog = "catalog"
    prices = "prices"
    images = "images"
    # Stale or incomplete cards fetched again one by one.
    refresh = "refresh"


class JobStatus(enum.StrEnum):
    # Started from the web UI, waiting for the worker to pick it up.
    queued = "queued"
    running = "running"
    success = "success"
    failed = "failed"
    # Stopped on purpose (a manual run took over).
    cancelled = "cancelled"


class JobTrigger(enum.StrEnum):
    # Started by the worker on its schedule.
    auto = "auto"
    # Started by an administrator (web UI) or the command line.
    manual = "manual"


class SyncRun(Base):
    __tablename__ = "sync_run"
    __table_args__ = (
        # At most one running job per game and kind.
        Index(
            "uq_sync_run_running",
            "game_id",
            "kind",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
        # At most one queued run per game and kind.
        Index(
            "uq_sync_run_queued",
            "game_id",
            "kind",
            unique=True,
            postgresql_where=text("status = 'queued'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("game.id"), index=True)
    kind: Mapped[JobKind] = mapped_column(Enum(JobKind, name="job_kind", native_enum=False))
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", native_enum=False, length=16),
        default=JobStatus.running,
    )
    trigger: Mapped[JobTrigger] = mapped_column(
        Enum(JobTrigger, name="job_trigger", native_enum=False, length=16),
        default=JobTrigger.manual,
        server_default=JobTrigger.manual,
    )
    # Process running the job ("api:<uuid>", "worker:<uuid>", "cli:<uuid>", None while
    # queued): a process that restarts fails the runs its previous instance left behind.
    owner: Mapped[str | None] = mapped_column(String(64))
    # Last progress (a batch stored, an image downloaded).
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set by a manual run that takes over; the owner stops the job.
    cancel_requested: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(String(2000))
