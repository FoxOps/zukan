from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    DDL,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    event,
    text,
)
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
    # Image download URL per language ({"en": url, "fr": url}).
    image_urls: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    # Cached image per language, relative to settings.image_dir. An empty path marks a
    # download the image server refused, so it is not retried on every view.
    image_paths: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
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
        Index(
            "ix_card_name_search_name_trgm",
            "search_name",
            postgresql_using="gin",
            postgresql_ops={"search_name": "gin_trgm_ops"},
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
    # Lower case without accents, for searches ("foret" finds "Forêt").
    search_name: Mapped[str] = mapped_column(
        String(255), Computed("lower(f_unaccent(name))", persisted=True)
    )


# `unaccent()` is not IMMUTABLE (its dictionary can change), so it cannot be used in a
# generated column directly; this wrapper pins the dictionary.
SEARCH_FUNCTIONS = [
    "CREATE EXTENSION IF NOT EXISTS unaccent",
    "CREATE OR REPLACE FUNCTION f_unaccent(text) RETURNS text "
    "LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT "
    "AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$",
]
for _statement in SEARCH_FUNCTIONS:
    event.listen(CardName.__table__, "before_create", DDL(_statement))
