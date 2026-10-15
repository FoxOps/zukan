"""feedback batch 4: refresh token rotation time, discrepancy arbitration

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
    op.add_column("catalog_discrepancy", sa.Column("resolution", sa.String(16), nullable=True))
    op.add_column("catalog_discrepancy", sa.Column("resolved_value", sa.String(500), nullable=True))
    op.add_column(
        "catalog_discrepancy",
        sa.Column(
            "resolved_by",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "catalog_discrepancy",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "catalog_discrepancy",
        sa.Column("by_rule", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_table(
        "catalog_field_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("game_id", sa.String(32), sa.ForeignKey("game.id"), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("field", sa.String(32), nullable=False),
        sa.Column("prefer", sa.String(16), nullable=False),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("game_id", "source", "field"),
    )


def downgrade() -> None:
    op.drop_table("catalog_field_rule")
    for column in ("by_rule", "resolved_at", "resolved_by", "resolved_value", "resolution"):
        op.drop_column("catalog_discrepancy", column)
    op.drop_column("refresh_token", "rotated_at")
