"""images per language, accent-free name search, user language and catalog games

Revision ID: 5a1c0e7f3b2d
Revises: 473d7ac3bdbe
Create Date: 2026-10-13 16:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.models.catalog import SEARCH_FUNCTIONS

revision: str = "5a1c0e7f3b2d"
down_revision: str | None = "473d7ac3bdbe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Language of the single image stored so far: English when the printing exists in
# English (full data always won), else its first language.
_IMAGE_LANG = "CASE WHEN 'en' = ANY(languages) THEN 'en' ELSE coalesce(languages[1], 'en') END"


def upgrade() -> None:
    empty = sa.text("'{}'::jsonb")
    op.add_column(
        "printing",
        sa.Column("image_urls", postgresql.JSONB(), server_default=empty, nullable=False),
    )
    op.add_column(
        "printing",
        sa.Column("image_paths", postgresql.JSONB(), server_default=empty, nullable=False),
    )
    op.execute(
        f"UPDATE printing SET image_urls = jsonb_build_object({_IMAGE_LANG}, image_url) "
        "WHERE image_url IS NOT NULL"
    )
    op.execute(
        f"UPDATE printing SET image_paths = jsonb_build_object({_IMAGE_LANG}, image_path) "
        "WHERE image_path IS NOT NULL"
    )
    op.drop_column("printing", "image_url")
    op.drop_column("printing", "image_path")

    for statement in SEARCH_FUNCTIONS:
        op.execute(statement)
    op.add_column(
        "card_name",
        sa.Column(
            "search_name",
            sa.String(length=255),
            sa.Computed("lower(f_unaccent(name))", persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_card_name_search_name_trgm",
        "card_name",
        ["search_name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"search_name": "gin_trgm_ops"},
    )

    op.add_column(
        "user",
        sa.Column("language", sa.String(length=8), server_default=sa.text("'en'"), nullable=False),
    )
    op.add_column("user", sa.Column("catalog_games", postgresql.ARRAY(sa.String(32))))


def downgrade() -> None:
    op.drop_column("user", "catalog_games")
    op.drop_column("user", "language")
    op.drop_index("ix_card_name_search_name_trgm", table_name="card_name")
    op.drop_column("card_name", "search_name")
    op.add_column("printing", sa.Column("image_path", sa.String(length=512)))
    op.add_column("printing", sa.Column("image_url", sa.String(length=1024)))
    op.execute(
        "UPDATE printing SET image_url = (SELECT value FROM jsonb_each_text(image_urls) "
        "ORDER BY key <> 'en' LIMIT 1), image_path = (SELECT value FROM "
        "jsonb_each_text(image_paths) WHERE value <> '' ORDER BY key <> 'en' LIMIT 1)"
    )
    op.drop_column("printing", "image_paths")
    op.drop_column("printing", "image_urls")
