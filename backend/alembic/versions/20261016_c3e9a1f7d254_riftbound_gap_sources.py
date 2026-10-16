"""Riftbound, gap-filling sources: API request quotas and checked sets, art series cards not double-faced

Revision ID: c3e9a1f7d254
Revises: b7d4e2a9c618
Create Date: 2026-10-16 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3e9a1f7d254"
down_revision: str | None = "b7d4e2a9c618"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("requests", sa.Integer(), server_default="0", nullable=False),
        sa.UniqueConstraint("source", "period_start"),
    )
    op.create_table(
        "gap_check",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("game_id", sa.String(32), nullable=False),
        sa.Column("set_external_id", sa.String(64), nullable=False),
        sa.Column("gaps", sa.Integer(), nullable=False),
        sa.Column("checked_on", sa.Date(), nullable=False),
        sa.UniqueConstraint("source", "game_id", "set_external_id"),
    )
    # MTG art series cards have two fronts, not a back face: no flip button. Attribute
    # merges keep stored keys, so the catalog sync alone would not drop it.
    op.execute(
        """
        UPDATE printing SET attributes = printing.attributes - 'back_image_url'
        FROM card
        WHERE printing.card_id = card.id
          AND card.attributes ->> 'layout' = 'art_series'
          AND printing.attributes ? 'back_image_url'
        """
    )


def downgrade() -> None:
    op.drop_table("gap_check")
    op.drop_table("api_usage")
