"""catalog discrepancies found by secondary sources

Revision ID: d71b2c94e6a0
Revises: c3a8e5f07b19
Create Date: 2026-10-14 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d71b2c94e6a0"
down_revision: str | None = "c3a8e5f07b19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_discrepancy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("game_id", sa.String(32), sa.ForeignKey("game.id"), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column(
            "set_id", sa.Integer(), sa.ForeignKey("card_set.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("printing_id", sa.Integer(), sa.ForeignKey("printing.id", ondelete="CASCADE")),
        sa.Column("field", sa.String(32), nullable=False),
        sa.Column("primary_value", sa.String(500)),
        sa.Column("secondary_value", sa.String(500)),
        sa.Column(
            "first_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_catalog_discrepancy_game_id", "catalog_discrepancy", ["game_id"])
    op.create_index("ix_catalog_discrepancy_printing_id", "catalog_discrepancy", ["printing_id"])
    op.create_index(
        "uq_catalog_discrepancy",
        "catalog_discrepancy",
        ["source", "set_id", "printing_id", "field"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_table("catalog_discrepancy")
