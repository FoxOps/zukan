"""optional modules per user, sets followed in the Binder module

Revision ID: a7c9e1f3b256
Revises: f3a5c7e9b124
Create Date: 2026-11-10 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a7c9e1f3b256"
down_revision: str | None = "f3a5c7e9b124"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column(
            "modules",
            postgresql.ARRAY(sa.String(32)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.create_table(
        "binder_set",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(8), nullable=True),
        sa.Column("finish", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name="fk_binder_set_user_id_user", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["set_id"], ["card_set.id"], name="fk_binder_set_set_id_card_set", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_binder_set"),
        sa.UniqueConstraint("user_id", "set_id", name="uq_binder_set_user_id_set_id"),
    )
    op.create_index("ix_binder_set_user_id", "binder_set", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_binder_set_user_id", table_name="binder_set")
    op.drop_table("binder_set")
    op.drop_column("user", "modules")
