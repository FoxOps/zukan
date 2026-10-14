"""job trigger, owner, heartbeat and cancel request

Revision ID: 7c2e9a41d5b8
Revises: 5a1c0e7f3b2d
Create Date: 2026-10-14 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7c2e9a41d5b8"
down_revision: str | None = "5a1c0e7f3b2d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # "cancelled" is longer than the statuses the column was sized for.
    op.alter_column("sync_run", "status", type_=sa.String(16), existing_nullable=False)
    # Earlier runs keep the worker's schedule: count them as automatic.
    op.add_column(
        "sync_run",
        sa.Column("trigger", sa.String(16), server_default="auto", nullable=False),
    )
    op.alter_column("sync_run", "trigger", server_default="manual")
    op.add_column("sync_run", sa.Column("owner", sa.String(64)))
    op.add_column("sync_run", sa.Column("heartbeat_at", sa.DateTime(timezone=True)))
    op.add_column(
        "sync_run",
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("sync_run", "cancel_requested")
    op.drop_column("sync_run", "heartbeat_at")
    op.drop_column("sync_run", "owner")
    op.drop_column("sync_run", "trigger")
    op.alter_column("sync_run", "status", type_=sa.String(7), existing_nullable=False)
