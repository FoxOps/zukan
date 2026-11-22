"""Shopping lists of the Decks module (`models.ShoppingList`): made on the web from a
deck's missing cards (`POST /api/decks/{id}/shopping-list`), ticked and deleted in the
Android app. Ticking a card only marks it bought; it does not change the collection."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import SessionDep
from app.models import ShoppingItem, ShoppingList, User
from app.modules import require_module

router = APIRouter(prefix="/shopping-lists", tags=["shopping"])

DecksUser = require_module("decks")


class ShoppingListOut(BaseModel):
    id: int
    # The deck's name when the list was made; the deck may be gone (`deck_id` None).
    name: str
    deck_id: int | None
    game_id: str
    created_at: datetime
    # Copies to get, and those ticked as bought.
    copies: int
    bought: int


class ShoppingItemOut(BaseModel):
    id: int
    card_id: int | None
    printing_id: int | None
    name: str
    translation: str | None
    set_code: str | None
    collector_number: str | None
    quantity: int
    # Copies ticked as bought (one box per copy).
    bought_count: int
    # All copies bought (what app versions before 0.19 read).
    bought: bool


class ShoppingListDetailOut(ShoppingListOut):
    items: list[ShoppingItemOut]


class ShoppingItemIn(BaseModel):
    # Copies bought, kept between 0 and the item's quantity.
    bought_count: int | None = None
    # All copies bought or none (app versions before 0.19), when `bought_count` is not given.
    bought: bool | None = None


def _list_out(found: ShoppingList, copies: int, bought: int) -> ShoppingListOut:
    return ShoppingListOut(
        id=found.id,
        name=found.name,
        deck_id=found.deck_id,
        game_id=found.game_id,
        created_at=found.created_at,
        copies=copies,
        bought=bought,
    )


async def shopping_detail(session: SessionDep, user: User, list_id: int) -> ShoppingListDetailOut:
    found = await session.scalar(
        select(ShoppingList)
        .where(ShoppingList.id == list_id, ShoppingList.user_id == user.id)
        .options(selectinload(ShoppingList.items))
        .execution_options(populate_existing=True)
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shopping list not found")
    out = _list_out(
        found,
        sum(i.quantity for i in found.items),
        sum(i.bought for i in found.items),
    )
    return ShoppingListDetailOut(
        **out.model_dump(),
        items=[
            ShoppingItemOut(
                id=i.id,
                card_id=i.card_id,
                printing_id=i.printing_id,
                name=i.name,
                translation=i.translation,
                set_code=i.set_code,
                collector_number=i.collector_number,
                quantity=i.quantity,
                bought_count=i.bought,
                bought=i.bought >= i.quantity,
            )
            for i in found.items
        ],
    )


@router.get("")
async def list_shopping_lists(user: DecksUser, session: SessionDep) -> list[ShoppingListOut]:
    """The user's shopping lists, newest first (complete ones too: only the user deletes
    them)."""
    rows = await session.execute(
        select(
            ShoppingList,
            func.coalesce(func.sum(ShoppingItem.quantity), 0),
            func.coalesce(func.sum(ShoppingItem.bought), 0),
        )
        .outerjoin(ShoppingItem)
        .where(ShoppingList.user_id == user.id)
        .group_by(ShoppingList.id)
        .order_by(ShoppingList.created_at.desc(), ShoppingList.id.desc())
    )
    return [_list_out(found, copies, bought) for found, copies, bought in rows]


@router.get("/{list_id}")
async def get_shopping_list(
    list_id: int, user: DecksUser, session: SessionDep
) -> ShoppingListDetailOut:
    return await shopping_detail(session, user, list_id)


@router.patch("/{list_id}/items/{item_id}")
async def update_shopping_item(
    list_id: int, item_id: int, body: ShoppingItemIn, user: DecksUser, session: SessionDep
) -> ShoppingListDetailOut:
    """Ticks copies of a card as bought, or not."""
    item = await session.scalar(
        select(ShoppingItem)
        .join(ShoppingList)
        .where(
            ShoppingItem.id == item_id,
            ShoppingItem.list_id == list_id,
            ShoppingList.user_id == user.id,
        )
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shopping list item not found")
    if body.bought_count is not None:
        item.bought = min(max(body.bought_count, 0), item.quantity)
    elif body.bought is not None:
        item.bought = item.quantity if body.bought else 0
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "bought_count is required")
    await session.commit()
    return await shopping_detail(session, user, list_id)


@router.delete("/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shopping_list(list_id: int, user: DecksUser, session: SessionDep) -> None:
    """Deletes a list (the Android app; the web never does)."""
    found = await session.scalar(
        select(ShoppingList).where(ShoppingList.id == list_id, ShoppingList.user_id == user.id)
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shopping list not found")
    await session.delete(found)
    await session.commit()
