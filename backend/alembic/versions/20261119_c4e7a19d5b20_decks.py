"""decks module: decklists, their cards and the owned copies allocated to them

Revision ID: c4e7a19d5b20
Revises: b8d0f2a4c367
Create Date: 2026-11-19 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4e7a19d5b20"
down_revision: str | None = "b8d0f2a4c367"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "deck",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("format", sa.String(32), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name="fk_deck_user_id_user", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["game_id"], ["game.id"], name="fk_deck_game_id_game"),
        sa.PrimaryKeyConstraint("id", name="pk_deck"),
    )
    op.create_index("ix_deck_user_id", "deck", ["user_id"])
    op.create_table(
        "deck_card",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deck_id", sa.Integer(), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["deck_id"], ["deck.id"], name="fk_deck_card_deck_id_deck", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["card_id"], ["card.id"], name="fk_deck_card_card_id_card", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_deck_card"),
        sa.UniqueConstraint(
            "deck_id", "card_id", "section", name="uq_deck_card_deck_id_card_id_section"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_deck_card_quantity_positive"),
    )
    op.create_index("ix_deck_card_card_id", "deck_card", ["card_id"])
    op.create_table(
        "deck_allocation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deck_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["deck_id"], ["deck.id"], name="fk_deck_allocation_deck_id_deck", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["collection_item.id"],
            name="fk_deck_allocation_item_id_collection_item",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_deck_allocation"),
        sa.UniqueConstraint("deck_id", "item_id", name="uq_deck_allocation_deck_id_item_id"),
        sa.CheckConstraint("quantity > 0", name="ck_deck_allocation_quantity_positive"),
    )
    op.create_index("ix_deck_allocation_item_id", "deck_allocation", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_deck_allocation_item_id", table_name="deck_allocation")
    op.drop_table("deck_allocation")
    op.drop_index("ix_deck_card_card_id", table_name="deck_card")
    op.drop_table("deck_card")
    op.drop_index("ix_deck_user_id", table_name="deck")
    op.drop_table("deck")
