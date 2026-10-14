"""card and printing last_seen_at, card refresh_attempted_at

Revision ID: 9b4f1d6e2a73
Revises: 7c2e9a41d5b8
Create Date: 2026-10-14 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9b4f1d6e2a73"
down_revision: str | None = "7c2e9a41d5b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Rows stored so far were seen by their game's last successful catalog sync.
_LAST_SYNC = """
    coalesce(
        (SELECT max(started_at) FROM sync_run
         WHERE sync_run.game_id = {table}.game_id AND kind = 'catalog' AND status = 'success'),
        now()
    )
"""


def upgrade() -> None:
    for table in ("card", "printing"):
        op.add_column(
            table,
            sa.Column(
                "last_seen_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
    op.execute(f"UPDATE card SET last_seen_at = {_LAST_SYNC.format(table='card')}")
    op.execute(
        "UPDATE printing SET last_seen_at = card.last_seen_at FROM card "
        "WHERE card.id = printing.card_id"
    )
    op.add_column("card", sa.Column("refresh_attempted_at", sa.DateTime(timezone=True)))
    op.create_index("ix_card_game_last_seen", "card", ["game_id", "last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_card_game_last_seen", table_name="card")
    op.drop_column("card", "refresh_attempted_at")
    op.drop_column("printing", "last_seen_at")
    op.drop_column("card", "last_seen_at")
