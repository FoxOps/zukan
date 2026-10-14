"""GIN index on card attributes (advanced search)

Revision ID: e5f9a7c13d42
Revises: d71b2c94e6a0
Create Date: 2026-10-14 20:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5f9a7c13d42"
down_revision: str | None = "d71b2c94e6a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_card_attributes",
        "card",
        ["attributes"],
        postgresql_using="gin",
        postgresql_ops={"attributes": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_card_attributes", table_name="card")
