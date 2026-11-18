import datetime as dt

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.catalog import Card
from app.models.collection import CollectionItem


class Deck(TimestampMixin, Base):
    """A decklist of the Decks module (`app.modules`), checked against its format's rules
    (`services.deck_rules`)."""

    __tablename__ = "deck"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("game.id"))
    name: Mapped[str] = mapped_column(String(100))
    # `services.deck_rules.FORMATS`.
    format: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    cards: Mapped[list["DeckCard"]] = relationship(
        back_populates="deck", cascade="all, delete-orphan", passive_deletes=True
    )


class DeckCard(Base):
    """Copies of a card the decklist asks for, in one section. Says nothing about the
    collection: owned copies are set aside with `DeckAllocation`."""

    __tablename__ = "deck_card"
    __table_args__ = (
        UniqueConstraint("deck_id", "card_id", "section"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Indexed by the unique constraint, which starts with it.
    deck_id: Mapped[int] = mapped_column(ForeignKey("deck.id", ondelete="CASCADE"))
    # Cards in decks are never pruned with the catalog: the sync fills them again (same
    # source id).
    card_id: Mapped[int] = mapped_column(ForeignKey("card.id", ondelete="RESTRICT"), index=True)
    # main | sideboard | commander
    section: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[int]

    deck: Mapped[Deck] = relationship(back_populates="cards")
    card: Mapped[Card] = relationship()


class DeckAllocation(TimestampMixin, Base):
    """Owned copies of a collection item set aside for a deck. The collection keeps its
    quantity; copies allocated to any deck are not available to the others
    (`services.decks`)."""

    __tablename__ = "deck_allocation"
    __table_args__ = (
        UniqueConstraint("deck_id", "item_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    deck_id: Mapped[int] = mapped_column(ForeignKey("deck.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(
        ForeignKey("collection_item.id", ondelete="CASCADE"), index=True
    )
    quantity: Mapped[int]

    item: Mapped[CollectionItem] = relationship()
