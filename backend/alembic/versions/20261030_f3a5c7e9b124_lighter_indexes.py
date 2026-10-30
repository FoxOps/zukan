"""Lighter indexes: drop the single-column indexes that a unique index already covers
(price snapshots by printing, printings by set, collection items by user); index printing
languages for the search language filter.

Revision ID: f3a5c7e9b124
Revises: e2f4a6b8c013
Create Date: 2026-10-30 12:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3a5c7e9b124"
down_revision: str | None = "e2f4a6b8c013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_price_snapshot_printing_id")
    op.execute("DROP INDEX IF EXISTS ix_collection_item_user_id")
    op.execute("DROP INDEX IF EXISTS ix_printing_set_id")
    op.create_index("ix_printing_languages", "printing", ["languages"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_printing_languages", table_name="printing")
    op.create_index("ix_printing_set_id", "printing", ["set_id"])
    op.create_index("ix_collection_item_user_id", "collection_item", ["user_id"])
    op.create_index("ix_price_snapshot_printing_id", "price_snapshot", ["printing_id"])
