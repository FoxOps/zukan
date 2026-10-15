"""feedback batch 4: refresh token rotation time

Revision ID: b7d4e2a9c618
Revises: f2a6c8e1b937
Create Date: 2026-10-15 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7d4e2a9c618"
down_revision: str | None = "f2a6c8e1b937"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "refresh_token", sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("refresh_token", "rotated_at")
