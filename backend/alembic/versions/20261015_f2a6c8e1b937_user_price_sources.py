"""user price sources: several, ordered, the first one for values

Revision ID: f2a6c8e1b937
Revises: e5f9a7c13d42
Create Date: 2026-10-15 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f2a6c8e1b937"
down_revision: str | None = "e5f9a7c13d42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "price_sources",
            postgresql.ARRAY(sa.String(32)),
            server_default=sa.text("'{cardmarket}'"),
            nullable=False,
        ),
    )
    op.execute('UPDATE "user" SET price_sources = ARRAY[price_source]')
    op.drop_column("user", "price_source")


def downgrade() -> None:
    op.add_column(
        "user",
        sa.Column("price_source", sa.String(32), server_default="cardmarket", nullable=False),
    )
    op.execute('UPDATE "user" SET price_source = price_sources[1]')
    op.drop_column("user", "price_sources")
