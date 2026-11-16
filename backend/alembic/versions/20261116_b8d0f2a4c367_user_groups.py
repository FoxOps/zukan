"""user groups giving access to optional modules

Revision ID: b8d0f2a4c367
Revises: a7c9e1f3b256
Create Date: 2026-11-16 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b8d0f2a4c367"
down_revision: str | None = "a7c9e1f3b256"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_group",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("builtin", sa.String(16), nullable=True),
        sa.Column(
            "idp_groups",
            postgresql.ARRAY(sa.String(255)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_group"),
        sa.UniqueConstraint("name", name="uq_user_group_name"),
        sa.UniqueConstraint("builtin", name="uq_user_group_builtin"),
    )
    op.create_table(
        "user_group_member",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["user_group.id"],
            name="fk_user_group_member_group_id_user_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name="fk_user_group_member_user_id_user", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("group_id", "user_id", name="pk_user_group_member"),
    )
    op.create_index("ix_user_group_member_user_id", "user_group_member", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_group_member_user_id", table_name="user_group_member")
    op.drop_table("user_group_member")
    op.drop_table("user_group")
