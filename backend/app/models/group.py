from sqlalchemy import Column, ForeignKey, String, Table, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.user import User

user_group_member = Table(
    "user_group_member",
    Base.metadata,
    Column("group_id", ForeignKey("user_group.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("user.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class UserGroup(TimestampMixin, Base):
    """Group of users given access to optional modules (`app.modules`), managed in
    Admin > Groups (`app.services.groups`).

    Members of a group linked to identity provider groups (`idp_groups`) are, for SSO
    accounts, those whose groups claim holds one of them at their last sign-in; local
    accounts are added by hand. The built-in Administrators group (`builtin="admins"`)
    holds no rows: its members are the users with the admin role."""

    __tablename__ = "user_group"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    builtin: Mapped[str | None] = mapped_column(String(16), unique=True)
    idp_groups: Mapped[list[str]] = mapped_column(
        ARRAY(String(255)), default=list, server_default=text("'{}'")
    )

    members: Mapped[list[User]] = relationship(
        secondary=user_group_member, passive_deletes=True, order_by=User.username
    )
