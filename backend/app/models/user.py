import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Role(enum.StrEnum):
    admin = "admin"
    user = "user"


class User(TimestampMixin, Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(150), unique=True)
    email: Mapped[str | None] = mapped_column(String(320))
    # Null for SSO-only accounts.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="user_role", native_enum=False), default=Role.user
    )
    disabled: Mapped[bool] = mapped_column(default=False)
    # Interface language; card images are shown in it when they exist.
    language: Mapped[str] = mapped_column(String(8), default="en", server_default=text("'en'"))
    # Games shown in the catalog, None for all of them.
    catalog_games: Mapped[list[str] | None] = mapped_column(ARRAY(String(32)))
    # Price sources (`app.prices` ids) shown, in order. The first one gives values, sorts
    # and price ranges; games without it use their first source.
    price_sources: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), default=lambda: ["cardmarket"], server_default=text("'{cardmarket}'")
    )

    @property
    def price_source(self) -> str:
        """Main price source."""
        return self.price_sources[0] if self.price_sources else "cardmarket"

    identities: Mapped[list["UserIdentity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def has_password(self) -> bool:
        return self.password_hash is not None


class UserIdentity(TimestampMixin, Base):
    """Link between a local user and an OIDC subject."""

    __tablename__ = "user_identity"
    __table_args__ = (UniqueConstraint("issuer", "subject"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    issuer: Mapped[str] = mapped_column(String(512))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))

    user: Mapped[User] = relationship(back_populates="identities")


class RefreshToken(TimestampMixin, Base):
    """Opaque rotating refresh token. Only the SHA-256 hash is stored.

    Tokens issued from one login share a family; reuse of a rotated token revokes the
    whole family (stolen token detection), except within a short grace period after the
    rotation (two tabs, or a reload during a refresh, present the same token).
    """

    __tablename__ = "refresh_token"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when the token was exchanged for a new one (not on logout).
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
