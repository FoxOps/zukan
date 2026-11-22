"""Shopping lists: `shopping_item.bought` counts the copies bought (one box per copy)
instead of ticking the whole line.

Revision ID: a8c2e5f9b064
Revises: f7b1d4e8a953
Create Date: 2026-11-22 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a8c2e5f9b064"
down_revision: str | None = "f7b1d4e8a953"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shopping_item",
        sa.Column("bought_copies", sa.Integer(), server_default="0", nullable=False),
    )
    op.execute("UPDATE shopping_item SET bought_copies = quantity WHERE bought")
    op.drop_column("shopping_item", "bought")
    op.alter_column("shopping_item", "bought_copies", new_column_name="bought")
    # Named by the metadata's convention: ck_shopping_item_bought_in_quantity.
    op.create_check_constraint(
        "bought_in_quantity", "shopping_item", "bought >= 0 AND bought <= quantity"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_shopping_item_bought_in_quantity"), "shopping_item")
    op.add_column(
        "shopping_item",
        sa.Column("bought_all", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute("UPDATE shopping_item SET bought_all = bought >= quantity")
    op.drop_column("shopping_item", "bought")
    op.alter_column("shopping_item", "bought_all", new_column_name="bought")
