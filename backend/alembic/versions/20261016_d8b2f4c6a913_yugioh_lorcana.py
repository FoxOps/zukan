"""Yu-Gi-Oh! and Lorcana: longer set ids (Yu-Gi-Oh! sets are keyed on their name) and
rarities ("Duel Terminal Normal Rare Parallel Rare")

Revision ID: d8b2f4c6a913
Revises: c3e9a1f7d254
Create Date: 2026-10-16 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d8b2f4c6a913"
down_revision: str | None = "c3e9a1f7d254"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("card_set", "external_id", type_=sa.String(128), existing_nullable=False)
    op.alter_column("gap_check", "set_external_id", type_=sa.String(128), existing_nullable=False)
    op.alter_column("printing", "rarity", type_=sa.String(64), existing_nullable=True)


def downgrade() -> None:
    op.alter_column("printing", "rarity", type_=sa.String(32), existing_nullable=True)
    op.alter_column("gap_check", "set_external_id", type_=sa.String(64), existing_nullable=False)
    op.alter_column("card_set", "external_id", type_=sa.String(64), existing_nullable=False)
