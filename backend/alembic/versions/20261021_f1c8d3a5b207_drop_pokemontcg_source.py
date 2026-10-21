"""Pokémon TCG API source removed: its catalog checks and field rules go, and so do the
English card pictures it filled (images.pokemontcg.io), with their cached files; the next
Pokémon catalog sync refills them from TCGdex and the gap-filling sources.

Revision ID: f1c8d3a5b207
Revises: e4a7c2d9b815
Create Date: 2026-10-21 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.config import get_settings

revision: str = "f1c8d3a5b207"
down_revision: str | None = "e4a7c2d9b815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HOST = "%//images.pokemontcg.io/%"


def upgrade() -> None:
    op.execute("DELETE FROM catalog_discrepancy WHERE source = 'pokemontcg'")
    op.execute("DELETE FROM catalog_field_rule WHERE source = 'pokemontcg'")
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT p.id, e.key, p.image_paths ->> e.key FROM printing p, "
            "jsonb_each_text(p.image_urls) AS e WHERE e.value LIKE :host"
        ),
        {"host": HOST},
    ).all()
    root = get_settings().image_dir.resolve()
    for _, _, path in rows:
        if not path:
            continue
        file = (root / path).resolve()
        if file.is_relative_to(root):
            file.unlink(missing_ok=True)
    for printing_id, lang, _ in rows:
        bind.execute(
            sa.text(
                "UPDATE printing SET image_urls = image_urls - :lang, "
                "image_paths = image_paths - :lang WHERE id = :id"
            ),
            {"lang": lang, "id": printing_id},
        )


def downgrade() -> None:
    # Removed data is not restored; the source itself is gone from the code.
    pass
