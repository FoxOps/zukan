"""Shopping lists (cards a deck misses, sent to the Android app) and `user.language_chosen`.
Accounts whose language is not English picked it; English ones cannot be told apart from
the default, so they follow the device or browser language until the user picks one.

Revision ID: f7b1d4e8a953
Revises: e6a9c3d7f842
Create Date: 2026-11-21 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f7b1d4e8a953"
down_revision: str | None = "e6a9c3d7f842"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("language_chosen", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute("UPDATE \"user\" SET language_chosen = true WHERE language <> 'en'")
    op.create_table(
        "shopping_list",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("deck_id", sa.Integer(), sa.ForeignKey("deck.id", ondelete="SET NULL")),
        sa.Column("game_id", sa.String(32), sa.ForeignKey("game.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_shopping_list_user_id", "shopping_list", ["user_id"])
    op.create_index("ix_shopping_list_deck_id", "shopping_list", ["deck_id"])
    op.create_table(
        "shopping_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "list_id",
            sa.Integer(),
            sa.ForeignKey("shopping_list.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), sa.ForeignKey("card.id", ondelete="SET NULL")),
        sa.Column("printing_id", sa.Integer(), sa.ForeignKey("printing.id", ondelete="SET NULL")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("translation", sa.String(255)),
        sa.Column("set_code", sa.String(32)),
        sa.Column("collector_number", sa.String(32)),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("bought", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_shopping_item_quantity_positive"),
    )
    op.create_index("ix_shopping_item_list_id", "shopping_item", ["list_id"])


def downgrade() -> None:
    op.drop_table("shopping_item")
    op.drop_table("shopping_list")
    op.drop_column("user", "language_chosen")
