from sqlalchemy import CheckConstraint, ForeignKey, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class ShoppingList(TimestampMixin, Base):
    """Cards a deck was missing when the user sent its shopping list to the Android app
    (Decks module): a copy, it does not follow later deck or collection changes. Only the
    app deletes lists, never the server on its own (not even complete ones)."""

    __tablename__ = "shopping_list"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    # The deck it was made from; the list stays when the deck is deleted.
    deck_id: Mapped[int | None] = mapped_column(
        ForeignKey("deck.id", ondelete="SET NULL"), index=True
    )
    game_id: Mapped[str] = mapped_column(ForeignKey("game.id"))
    # The deck's name when the list was made.
    name: Mapped[str] = mapped_column(String(100))

    items: Mapped[list["ShoppingItem"]] = relationship(
        back_populates="shopping_list",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ShoppingItem.position",
    )


class ShoppingItem(Base):
    """Copies of a card to buy. Names and set are kept as they were, so the list reads
    the same after catalog changes; `card_id` / `printing_id` (None once gone from the
    catalog) leave room to add bought cards to the collection later."""

    __tablename__ = "shopping_item"
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    list_id: Mapped[int] = mapped_column(
        ForeignKey("shopping_list.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    card_id: Mapped[int | None] = mapped_column(ForeignKey("card.id", ondelete="SET NULL"))
    # The printing the deck asks for, None: any.
    printing_id: Mapped[int | None] = mapped_column(ForeignKey("printing.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(255))
    # Name in the user's language, when it differs.
    translation: Mapped[str | None] = mapped_column(String(255))
    set_code: Mapped[str | None] = mapped_column(String(32))
    collector_number: Mapped[str | None] = mapped_column(String(32))
    quantity: Mapped[int]
    bought: Mapped[bool] = mapped_column(default=False, server_default=false())

    shopping_list: Mapped[ShoppingList] = relationship(back_populates="items")
