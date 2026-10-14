"""price sources: snapshot source ids, market ids per printing, user price source

Revision ID: c3a8e5f07b19
Revises: 9b4f1d6e2a73
Create Date: 2026-10-14 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3a8e5f07b19"
down_revision: str | None = "9b4f1d6e2a73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every source so far was Cardmarket, named after the API that carried its prices.
    op.execute(
        "UPDATE price_snapshot SET source = 'cardmarket' "
        "WHERE source IN ('scryfall-cardmarket', 'tcgdex-cardmarket')"
    )
    op.execute(
        "UPDATE printing SET attributes = (attributes - 'cardmarket_id') || "
        "jsonb_build_object('market_ids', jsonb_build_object('cardmarket', "
        "attributes -> 'cardmarket_id')) "
        "WHERE attributes ? 'cardmarket_id'"
    )
    op.add_column(
        "user",
        sa.Column("price_source", sa.String(32), server_default="cardmarket", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("user", "price_source")
    op.execute(
        "UPDATE printing SET attributes = (attributes - 'market_ids') || "
        "jsonb_build_object('cardmarket_id', attributes -> 'market_ids' -> 'cardmarket') "
        "WHERE attributes -> 'market_ids' ? 'cardmarket'"
    )
    op.execute("DELETE FROM price_snapshot WHERE source <> 'cardmarket'")
