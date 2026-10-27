"""Runs started from the web UI wait in a queue for the worker: at most one queued run
per game and kind.

Revision ID: e2f4a6b8c013
Revises: d7a9c1e3f546
Create Date: 2026-10-27 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2f4a6b8c013"
down_revision: str | None = "d7a9c1e3f546"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_sync_run_queued",
        "sync_run",
        ["game_id", "kind"],
        unique=True,
        postgresql_where=sa.text("status = 'queued'"),
    )


def downgrade() -> None:
    op.execute("UPDATE sync_run SET status = 'failed' WHERE status = 'queued'")
    op.drop_index(
        "uq_sync_run_queued", table_name="sync_run", postgresql_where=sa.text("status = 'queued'")
    )
