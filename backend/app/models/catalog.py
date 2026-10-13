from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Game(Base):
    __tablename__ = "game"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    last_catalog_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_price_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CardSet(Base):
    __tablename__ = "card_set"
    __table_args__ = (UniqueConstraint("game_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("game.id"), index=True)
    # Provider-specific unique id; `code` is what is printed on cards and may collide
    # across languages (e.g. Pokémon EN/JA sets).
    external_id: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(255))
    lang: Mapped[str | None] = mapped_column(String(8))
    release_date: Mapped[date | None] = mapped_column(Date)
    total: Mapped[int | None]
    icon_url: Mapped[str | None] = mapped_column(String(1024))


class Card(Base):
    """Game-level card (same rules/name across all printings)."""

    __tablename__ = "card"
    __table_args__ = (UniqueConstraint("game_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("game.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(255), index=True)
    # Normalized color codes from the provider's color vocabulary.
    colors: Mapped[list[str]] = mapped_column(ARRAY(String(16)), default=list)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    printings: Mapped[list["Printing"]] = relationship(back_populates="card")


class Printing(Base):
    """A card as printed in one set (one edition)."""

    __tablename__ = "printing"
    __table_args__ = (UniqueConstraint("set_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("card.id", ondelete="CASCADE"), index=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("card_set.id", ondelete="CASCADE"), index=True)
    external_id: Mapped[str] = mapped_column(String(128))
    collector_number: Mapped[str | None] = mapped_column(String(32), index=True)
    rarity: Mapped[str | None] = mapped_column(String(32))
    artist: Mapped[str | None] = mapped_column(String(255))
    finishes: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(8)), default=list)
    image_url: Mapped[str | None] = mapped_column(String(1024))
    # Path relative to settings.image_dir once cached.
    image_path: Mapped[str | None] = mapped_column(String(512))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    card: Mapped[Card] = relationship(back_populates="printings")
    set: Mapped[CardSet] = relationship()


class CardName(Base):
    """Localized names, searched with trigram similarity for OCR matching."""

    __tablename__ = "card_name"
    __table_args__ = (
        UniqueConstraint(
            "card_id", "printing_id", "lang", "name", postgresql_nulls_not_distinct=True
        ),
        Index(
            "ix_card_name_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("card.id", ondelete="CASCADE"), index=True)
    # Null when the name applies to every printing of the card.
    printing_id: Mapped[int | None] = mapped_column(
        ForeignKey("printing.id", ondelete="CASCADE"), index=True
    )
    lang: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(255))
