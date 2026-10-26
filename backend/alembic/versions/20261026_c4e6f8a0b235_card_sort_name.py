"""Card sort name: whole catalogs sort by the card's Latin name, cards known only by
non-Latin names last (see `app.services.names.update_sort_names`).

Revision ID: c4e6f8a0b235
Revises: b3d5e7f9a124
Create Date: 2026-10-26 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.services.names import sort_name_query

revision: str = "c4e6f8a0b235"
down_revision: str | None = "b3d5e7f9a124"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("card", sa.Column("sort_name", sa.String(length=255), nullable=True))
    op.execute(sort_name_query())
    op.create_index("ix_card_sort_name", "card", ["sort_name", "name", "id"])
    op.create_index(
        "ix_card_sort_name_desc",
        "card",
        [sa.text("sort_name DESC NULLS LAST"), sa.text("name DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_card_sort_name_desc", table_name="card")
    op.drop_index("ix_card_sort_name", table_name="card")
    op.drop_column("card", "sort_name")
