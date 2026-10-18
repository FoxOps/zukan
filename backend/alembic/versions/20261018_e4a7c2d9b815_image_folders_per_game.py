"""Image folders per game: `<game>/cards`, `<game>/sets`, `<game>/symbols`,
`<game>/rarity` (see `app.services.layout`). Moves the cached files and rewrites the card
paths stored on printings.

Revision ID: e4a7c2d9b815
Revises: d8b2f4c6a913
Create Date: 2026-10-18 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.config import get_settings
from app.services import layout

revision: str = "e4a7c2d9b815"
down_revision: str | None = "d8b2f4c6a913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rewrite_paths(pattern: str, replacement: str) -> None:
    op.execute(
        sa.text(layout.REWRITE_PATHS_SQL).bindparams(pattern=pattern, replacement=replacement)
    )


def upgrade() -> None:
    layout.move_to_game_folders(get_settings().image_dir)
    _rewrite_paths(*layout.TO_GAME_FOLDERS)


def downgrade() -> None:
    layout.move_to_old_folders(get_settings().image_dir)
    _rewrite_paths(*layout.TO_OLD_FOLDERS)
