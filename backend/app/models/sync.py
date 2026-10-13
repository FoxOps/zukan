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


class JobStatus(enum.StrEnum):
    running = "running"
    success = "success"
    failed = "failed"


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
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("game.id"), index=True)
    kind: Mapped[JobKind] = mapped_column(Enum(JobKind, name="job_kind", native_enum=False))
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", native_enum=False), default=JobStatus.running
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(String(2000))
