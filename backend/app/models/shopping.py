from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class ShoppingList(TimestampMixin, Base):
    """Cards to buy, for every user (no module needed). A list is either standalone
    (made and edited on the web) or linked to one source: a deck (Decks module) or a
    followed set (Binder module). A linked list is rebuilt from its source only when the
    user asks (`services.shopping.sync_source`); it becomes standalone when the source is
    deleted. A user has at most one list per source (the partial unique indexes)."""

    __tablename__ = "shopping_list"
    __table_args__ = (
        Index(
            "uq_shopping_list_user_deck",
            "user_id",
            "deck_id",
            unique=True,
            postgresql_where=text("deck_id IS NOT NULL"),
        ),
        Index(
            "uq_shopping_list_user_binder",
            "user_id",
            "binder_id",
            unique=True,
            postgresql_where=text("binder_id IS NOT NULL"),
        ),
        CheckConstraint("deck_id IS NULL OR binder_id IS NULL", name="one_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    # The source it is linked to, None: standalone. The list stays when the source goes.
    deck_id: Mapped[int | None] = mapped_column(
        ForeignKey("deck.id", ondelete="SET NULL"), index=True
    )
    binder_id: Mapped[int | None] = mapped_column(
        ForeignKey("binder_set.id", ondelete="SET NULL"), index=True
    )
    game_id: Mapped[str] = mapped_column(ForeignKey("game.id"))
    # Given by the user, or the source's name when the list was made.
    name: Mapped[str] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list["ShoppingItem"]] = relationship(
        back_populates="shopping_list",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ShoppingItem.position",
    )


class ShoppingItem(Base):
    """Copies of a card to buy, in any of the accepted editions (`editions`; none: any
    edition). "2 Lightning Bolt from A or B" is two copies in any mix. Names and editions
    are kept as they were, so the list reads the same after catalog changes."""

    __tablename__ = "shopping_item"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("bought >= 0 AND bought <= quantity", name="bought_in_quantity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(
        ForeignKey("shopping_list.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    card_id: Mapped[int | None] = mapped_column(ForeignKey("card.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(255))
    # Name in the user's language, when it differs.
    translation: Mapped[str | None] = mapped_column(String(255))
    # Copies must be in this language / finish (followed sets); None: any.
    language: Mapped[str | None] = mapped_column(String(8))
    finish: Mapped[str | None] = mapped_column(String(32))
    quantity: Mapped[int]
    # Copies ticked as bought, one box per copy (0 to `quantity`).
    bought: Mapped[int] = mapped_column(default=0, server_default="0")
    # Copies the source asked for at the last refresh; None: added by hand. A refresh
    # asking fewer removes ticked copies first (a bought copy reached the collection).
    source_quantity: Mapped[int | None]

    shopping_list: Mapped[ShoppingList] = relationship(back_populates="items")
    editions: Mapped[list["ShoppingEdition"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ShoppingEdition.position",
        lazy="selectin",
    )


class ShoppingEdition(Base):
    """An edition accepted for a shopping item, with its set and number kept as they
    were (`printing_id` None once gone from the catalog)."""

    __tablename__ = "shopping_edition"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("shopping_item.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(default=0)
    printing_id: Mapped[int | None] = mapped_column(ForeignKey("printing.id", ondelete="SET NULL"))
    set_code: Mapped[str | None] = mapped_column(String(32))
    collector_number: Mapped[str | None] = mapped_column(String(32))

    item: Mapped[ShoppingItem] = relationship(back_populates="editions")
