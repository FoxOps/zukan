"""Pokémon and Yu-Gi-Oh! split by market: Pokémon TCG Asia, Pokémon TCG China and
Yu-Gi-Oh! OCG become games of their own. Their sets, printings, owned copies and cached
pictures move there (see `app.services.split`).

Revision ID: b3d5e7f9a124
Revises: a6e2b9d4c713
Create Date: 2026-10-23 10:00:00
"""

import logging
from collections.abc import Sequence

from alembic import op
from app.core.config import get_settings
from app.services.split import split_games

revision: str = "b3d5e7f9a124"
down_revision: str | None = "a6e2b9d4c713"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    report = split_games(op.get_bind(), get_settings().image_dir)
    log.info("Games split by market: %s", report)


def downgrade() -> None:
    # Merging the games back would mix printings the split separated: not undone.
    raise NotImplementedError("The split of the Pokémon and Yu-Gi-Oh! games is not undone")
