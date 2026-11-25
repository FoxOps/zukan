"""Shopping lists for every user: standalone lists, lists linked to a deck or a followed
set (at most one per source), accepted editions per item (`shopping_edition`), language
and finish requirements, and the source's quantity at the last refresh.

Existing lists keep their ids, contents and ticks. A deck with several lists is an
ambiguous source: those lists become standalone.

Revision ID: b3d7f1a9c206
Revises: a8c2e5f9b064
Create Date: 2026-11-25 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3d7f1a9c206"
down_revision: str | None = "a8c2e5f9b064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shopping_list",
        sa.Column("binder_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_shopping_list_binder_id_binder_set"),
        "shopping_list",
        "binder_set",
        ["binder_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_shopping_list_binder_id"), "shopping_list", ["binder_id"])
    op.add_column(
        "shopping_list",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.execute("UPDATE shopping_list SET updated_at = created_at")
    op.create_check_constraint(
        "one_source", "shopping_list", "deck_id IS NULL OR binder_id IS NULL"
    )

    op.create_table(
        "shopping_edition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("printing_id", sa.Integer(), nullable=True),
        sa.Column("set_code", sa.String(length=32), nullable=True),
        sa.Column("collector_number", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["shopping_item.id"],
            name=op.f("fk_shopping_edition_item_id_shopping_item"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["printing_id"],
            ["printing.id"],
            name=op.f("fk_shopping_edition_printing_id_printing"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shopping_edition")),
    )
    op.create_index(op.f("ix_shopping_edition_item_id"), "shopping_edition", ["item_id"])
    # The edition each item asked for (printing kept, or only its set and number left).
    op.execute(
        "INSERT INTO shopping_edition (item_id, position, printing_id, set_code, collector_number) "
        "SELECT id, 0, printing_id, set_code, collector_number FROM shopping_item "
        "WHERE printing_id IS NOT NULL OR set_code IS NOT NULL OR collector_number IS NOT NULL"
    )

    op.add_column("shopping_item", sa.Column("language", sa.String(length=8), nullable=True))
    op.add_column("shopping_item", sa.Column("finish", sa.String(length=32), nullable=True))
    op.add_column("shopping_item", sa.Column("source_quantity", sa.Integer(), nullable=True))

    # A deck with several lists: none of them is its list.
    op.execute(
        "UPDATE shopping_list SET deck_id = NULL WHERE deck_id IN ("
        "SELECT deck_id FROM shopping_list WHERE deck_id IS NOT NULL "
        "GROUP BY user_id, deck_id HAVING count(*) > 1)"
    )
    op.execute(
        "UPDATE shopping_item SET source_quantity = quantity WHERE list_id IN ("
        "SELECT id FROM shopping_list WHERE deck_id IS NOT NULL)"
    )
    op.create_index(
        "uq_shopping_list_user_deck",
        "shopping_list",
        ["user_id", "deck_id"],
        unique=True,
        postgresql_where=sa.text("deck_id IS NOT NULL"),
    )
    op.create_index(
        "uq_shopping_list_user_binder",
        "shopping_list",
        ["user_id", "binder_id"],
        unique=True,
        postgresql_where=sa.text("binder_id IS NOT NULL"),
    )

    op.drop_constraint(
        op.f("fk_shopping_item_printing_id_printing"), "shopping_item", type_="foreignkey"
    )
    op.drop_column("shopping_item", "printing_id")
    op.drop_column("shopping_item", "set_code")
    op.drop_column("shopping_item", "collector_number")


def downgrade() -> None:
    op.add_column(
        "shopping_item", sa.Column("collector_number", sa.String(length=32), nullable=True)
    )
    op.add_column("shopping_item", sa.Column("set_code", sa.String(length=32), nullable=True))
    op.add_column("shopping_item", sa.Column("printing_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_shopping_item_printing_id_printing"),
        "shopping_item",
        "printing",
        ["printing_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Only one edition fits: the first.
    op.execute(
        "UPDATE shopping_item i SET printing_id = e.printing_id, set_code = e.set_code, "
        "collector_number = e.collector_number FROM shopping_edition e "
        "WHERE e.item_id = i.id AND e.position = ("
        "SELECT min(position) FROM shopping_edition WHERE item_id = i.id)"
    )
    op.drop_index("uq_shopping_list_user_binder", table_name="shopping_list")
    op.drop_index("uq_shopping_list_user_deck", table_name="shopping_list")
    op.drop_column("shopping_item", "source_quantity")
    op.drop_column("shopping_item", "finish")
    op.drop_column("shopping_item", "language")
    op.drop_index(op.f("ix_shopping_edition_item_id"), table_name="shopping_edition")
    op.drop_table("shopping_edition")
    op.drop_constraint(op.f("ck_shopping_list_one_source"), "shopping_list")
    op.drop_column("shopping_list", "updated_at")
    op.drop_index(op.f("ix_shopping_list_binder_id"), table_name="shopping_list")
    op.drop_constraint(
        op.f("fk_shopping_list_binder_id_binder_set"), "shopping_list", type_="foreignkey"
    )
    op.drop_column("shopping_list", "binder_id")
