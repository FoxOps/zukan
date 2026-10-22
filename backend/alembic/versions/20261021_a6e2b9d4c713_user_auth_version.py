"""`user.auth_version`, carried by access tokens and raised when a password changes or an
account is disabled, which ends every session of the account.

Revision ID: a6e2b9d4c713
Revises: f1c8d3a5b207
Create Date: 2026-10-21 11:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a6e2b9d4c713"
down_revision: str | None = "f1c8d3a5b207"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user", sa.Column("auth_version", sa.Integer(), server_default="0", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("user", "auth_version")
