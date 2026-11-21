"""SSO sessions (absolute lifetime, identity provider recheck) and single-use app ID
tokens. Open SSO sessions get their sign-in time from their first refresh token (rows
are never deleted), so only those already past the lifetime end; they are not checked at
the provider until the next sign-in (no provider refresh token was kept).

Revision ID: e6a9c3d7f842
Revises: d5f8b2c6e731
Create Date: 2026-11-21 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e6a9c3d7f842"
down_revision: str | None = "d5f8b2c6e731"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sso_session",
        sa.Column("family_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idp_refresh_token", sa.String(4096)),
    )
    op.create_index("ix_sso_session_user_id", "sso_session", ["user_id"])
    op.create_table(
        "used_id_token",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_used_id_token_expires_at", "used_id_token", ["expires_at"])
    op.execute(
        """
        INSERT INTO sso_session (family_id, user_id, provider, started_at, checked_at)
        SELECT t.family_id, t.user_id, i.provider, min(t.created_at), now()
        FROM refresh_token t
        JOIN (
            SELECT user_id, min(provider) AS provider FROM user_identity GROUP BY user_id
        ) i ON i.user_id = t.user_id
        WHERE t.family_id IN (
            SELECT family_id FROM refresh_token
            WHERE revoked_at IS NULL AND expires_at > now()
        )
        GROUP BY t.family_id, t.user_id, i.provider
        """
    )


def downgrade() -> None:
    op.drop_table("used_id_token")
    op.drop_table("sso_session")
