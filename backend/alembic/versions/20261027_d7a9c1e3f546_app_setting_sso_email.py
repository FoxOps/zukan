"""App settings edited in the web interface (sync schedule), and SSO users' email:
accounts without one take the address their identity provider last sent.

Revision ID: d7a9c1e3f546
Revises: c4e6f8a0b235
Create Date: 2026-10-27 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d7a9c1e3f546"
down_revision: str | None = "c4e6f8a0b235"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_setting",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_setting")),
    )
    op.execute(
        """
        UPDATE "user" SET email = latest.email
        FROM (
            SELECT DISTINCT ON (user_id) user_id, email FROM user_identity
            WHERE email IS NOT NULL ORDER BY user_id, id DESC
        ) AS latest
        WHERE "user".id = latest.user_id AND "user".email IS NULL
        """
    )


def downgrade() -> None:
    op.drop_table("app_setting")
