"""decks: a deck line can ask for one printing of its card

Revision ID: d5f8b2c6e731
Revises: c4e7a19d5b20
Create Date: 2026-11-19 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d5f8b2c6e731"
down_revision: str | None = "c4e7a19d5b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("deck_card", sa.Column("printing_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_deck_card_printing_id_printing",
        "deck_card",
        "printing",
        ["printing_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_deck_card_printing_id", "deck_card", ["printing_id"])
    op.drop_constraint("uq_deck_card_deck_id_card_id_section", "deck_card", type_="unique")
    op.create_unique_constraint(
        "uq_deck_card_deck_id_card_id_section_printing_id",
        "deck_card",
        ["deck_id", "card_id", "section", "printing_id"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    # Lines of one card and section are added up into one "any printing" line.
    op.execute(
        """
        WITH merged AS (
            SELECT min(id) AS keep, deck_id, card_id, section, sum(quantity) AS total
            FROM deck_card GROUP BY deck_id, card_id, section
        )
        UPDATE deck_card SET quantity = merged.total
        FROM merged WHERE deck_card.id = merged.keep
        """
    )
    op.execute(
        """
        DELETE FROM deck_card d USING deck_card k
        WHERE d.deck_id = k.deck_id AND d.card_id = k.card_id AND d.section = k.section
          AND d.id > k.id
        """
    )
    op.drop_constraint(
        "uq_deck_card_deck_id_card_id_section_printing_id", "deck_card", type_="unique"
    )
    op.create_unique_constraint(
        "uq_deck_card_deck_id_card_id_section", "deck_card", ["deck_id", "card_id", "section"]
    )
    op.drop_index("ix_deck_card_printing_id", "deck_card")
    op.drop_constraint("fk_deck_card_printing_id_printing", "deck_card", type_="foreignkey")
    op.drop_column("deck_card", "printing_id")
