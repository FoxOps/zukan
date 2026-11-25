"""Asian and Chinese Pokémon cards: drop their card-level Latin names (English, French,
German, Italian, Spanish, Portuguese).

Korean, Chinese, Thai and Indonesian cards were joined to stored printings by number
alone; in promo sets each source numbers its own way, so another card's Latin names were
added to the stored card ("ピカチュウ (Salamèche)"). Partial syncs only add names, so they
never went away. Every Latin name of these games comes from those joins and the
international names of their English card: the next sync (Pokémon `catalog_version` 12,
run in full) writes them again, joins checked.

Downgrade: nothing to restore (the names come back with a sync).

Revision ID: c4e8a2d6f317
Revises: b3d7f1a9c206
Create Date: 2026-11-25 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4e8a2d6f317"
down_revision: str | None = "b3d7f1a9c206"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM card_name n
            USING card c
            WHERE n.card_id = c.id
              AND n.printing_id IS NULL
              AND c.game_id IN ('pokemon-asia', 'pokemon-china')
              AND split_part(lower(n.lang), '-', 1) IN ('en', 'fr', 'de', 'it', 'es', 'pt')
            """
        )
    )


def downgrade() -> None:
    pass
