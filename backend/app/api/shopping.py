"""Shopping lists (`models.ShoppingList`), for every signed-in user whatever their
modules: standalone lists made and edited on the web, and lists linked to a deck
(`POST /api/decks/{id}/shopping-list`) or a followed set (`POST /api/binder/{id}/
shopping-list`). Copies are ticked on the web and in the Android app; ticking only marks
a copy bought, it does not change the collection or the decks."""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.catalog import load_names, show_card
from app.api.deps import CurrentUser, SessionDep
from app.models import Card, Game, Printing, ShoppingItem, ShoppingList, User
from app.services import shopping
from app.services.shopping import Edition

router = APIRouter(prefix="/shopping-lists", tags=["shopping"])

# Copies of one card in a list, at most.
MAX_QUANTITY = 999


class ShoppingListOut(BaseModel):
    id: int
    name: str
    # The source the list is linked to, None: standalone (or the source is gone).
    source: Literal["deck", "binder"] | None
    deck_id: int | None
    binder_id: int | None
    game_id: str
    created_at: datetime
    updated_at: datetime
    # Copies to get, and those ticked as bought.
    copies: int
    bought: int


class EditionOut(BaseModel):
    printing_id: int | None
    set_code: str | None
    collector_number: str | None


class ShoppingItemOut(BaseModel):
    id: int
    card_id: int | None
    # Accepted editions, empty: any.
    editions: list[EditionOut]
    # The edition when only one is accepted (app versions before 0.21 read these three).
    printing_id: int | None
    # With several editions: all of them ("M10 146 / 2X2 117"), `collector_number` None.
    set_code: str | None
    collector_number: str | None
    name: str
    translation: str | None
    # Copies must be in this language / finish; None: any.
    language: str | None
    finish: str | None
    quantity: int
    # Copies ticked as bought (one box per copy).
    bought_count: int
    # All copies bought (what app versions before 0.19 read).
    bought: bool
    # Added by hand: the next refresh of a linked list removes it.
    manual: bool


class ShoppingListDetailOut(ShoppingListOut):
    items: list[ShoppingItemOut]


class ShoppingListIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    game_id: str


class ShoppingListUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ShoppingItemAddIn(BaseModel):
    card_id: int
    quantity: int = Field(default=1, ge=1, le=MAX_QUANTITY)
    # Accepted printings of the card, empty: any.
    printing_ids: list[int] = []


class ShoppingItemIn(BaseModel):
    """Fields left out are not changed."""

    # Copies bought, kept between 0 and the item's quantity.
    bought_count: int | None = None
    # All copies bought or none (app versions before 0.19), when `bought_count` is not given.
    bought: bool | None = None
    quantity: int | None = Field(default=None, ge=1, le=MAX_QUANTITY)
    # Accepted printings of the card, empty: any.
    printing_ids: list[int] | None = None


def _source(found: ShoppingList) -> Literal["deck", "binder"] | None:
    if found.deck_id is not None:
        return "deck"
    if found.binder_id is not None:
        return "binder"
    return None


def _list_out(found: ShoppingList, copies: int, bought: int) -> ShoppingListOut:
    return ShoppingListOut(
        id=found.id,
        name=found.name,
        source=_source(found),
        deck_id=found.deck_id,
        binder_id=found.binder_id,
        game_id=found.game_id,
        created_at=found.created_at,
        updated_at=found.updated_at,
        copies=copies,
        bought=bought,
    )


def _item_out(item: ShoppingItem) -> ShoppingItemOut:
    editions = shopping.item_editions(item)
    one = editions[0] if len(editions) == 1 else None
    return ShoppingItemOut(
        id=item.id,
        card_id=item.card_id,
        editions=[EditionOut(**e.__dict__) for e in editions],
        printing_id=one.printing_id if one else None,
        set_code=(
            one.set_code if one else " / ".join(e.label() for e in editions if e.label()) or None
        ),
        collector_number=one.collector_number if one else None,
        name=item.name,
        translation=item.translation,
        language=item.language,
        finish=item.finish,
        quantity=item.quantity,
        bought_count=item.bought,
        bought=item.bought >= item.quantity,
        manual=item.source_quantity is None,
    )


async def _load(session: SessionDep, user: User, list_id: int) -> ShoppingList:
    found = await session.scalar(
        select(ShoppingList)
        .where(ShoppingList.id == list_id, ShoppingList.user_id == user.id)
        .options(selectinload(ShoppingList.items))
        .execution_options(populate_existing=True)
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shopping list not found")
    return found


async def shopping_detail(session: SessionDep, user: User, list_id: int) -> ShoppingListDetailOut:
    found = await _load(session, user, list_id)
    out = _list_out(
        found,
        sum(i.quantity for i in found.items),
        sum(i.bought for i in found.items),
    )
    return ShoppingListDetailOut(**out.model_dump(), items=[_item_out(i) for i in found.items])


async def _item(session: SessionDep, user: User, list_id: int, item_id: int) -> ShoppingItem:
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
    return item


async def _editions(session: SessionDep, card: Card, printing_ids: list[int]) -> list[Edition]:
    """The card's printings asked for, in the order given; 422 for another card's."""
    wanted = list(dict.fromkeys(printing_ids))
    if not wanted:
        return []
    printings = {
        p.id: p
        for p in await session.scalars(
            select(Printing)
            .where(Printing.id.in_(wanted), Printing.card_id == card.id)
            .options(selectinload(Printing.set))
        )
    }
    if len(printings) != len(wanted):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown printing")
    return [
        Edition(p.id, p.set.code.upper(), p.collector_number)
        for p in (printings[i] for i in wanted)
    ]


@router.get("")
async def list_shopping_lists(user: CurrentUser, session: SessionDep) -> list[ShoppingListOut]:
    """The user's shopping lists, newest first (complete ones too: only the user deletes
    them, or a refresh of a linked list with nothing left to buy)."""
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


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_shopping_list(
    body: ShoppingListIn, user: CurrentUser, session: SessionDep
) -> ShoppingListDetailOut:
    """A standalone list, empty until cards are added."""
    if await session.get(Game, body.game_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown game")
    found = ShoppingList(user_id=user.id, game_id=body.game_id, name=body.name.strip())
    session.add(found)
    await session.commit()
    return await shopping_detail(session, user, found.id)


@router.get("/{list_id}")
async def get_shopping_list(
    list_id: int, user: CurrentUser, session: SessionDep
) -> ShoppingListDetailOut:
    return await shopping_detail(session, user, list_id)


@router.patch("/{list_id}")
async def rename_shopping_list(
    list_id: int, body: ShoppingListUpdateIn, user: CurrentUser, session: SessionDep
) -> ShoppingListDetailOut:
    found = await _load(session, user, list_id)
    found.name = body.name.strip()
    await session.commit()
    return await shopping_detail(session, user, list_id)


@router.post("/{list_id}/items", status_code=status.HTTP_201_CREATED)
async def add_shopping_item(
    list_id: int, body: ShoppingItemAddIn, user: CurrentUser, session: SessionDep
) -> ShoppingListDetailOut:
    """Adds copies of a card of the list's game, at the end of the list."""
    found = await _load(session, user, list_id)
    card = await session.scalar(
        select(Card)
        .where(Card.id == body.card_id, Card.game_id == found.game_id)
        .options(selectinload(Card.printings).selectinload(Printing.set))
    )
    if card is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown card")
    editions = await _editions(session, card, body.printing_ids)
    card_names, printing_names = await load_names(session, {card.id})
    translation = show_card(card, card_names, printing_names, user.language).name.name
    line = shopping.ShoppingLine(
        card_id=card.id,
        name=card.name,
        translation=translation if translation != card.name else None,
        quantity=body.quantity,
        editions=editions,
    )
    position = max((i.position for i in found.items), default=-1) + 1
    found.items.append(shopping.new_item(line, position, from_source=False))
    await session.commit()
    return await shopping_detail(session, user, list_id)


@router.patch("/{list_id}/items/{item_id}")
async def update_shopping_item(
    list_id: int, item_id: int, body: ShoppingItemIn, user: CurrentUser, session: SessionDep
) -> ShoppingListDetailOut:
    """Ticks copies of a card as bought or not, changes its copies or editions."""
    item = await _item(session, user, list_id, item_id)
    fields = body.model_dump(exclude_unset=True)
    if not {k for k, v in fields.items() if v is not None}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "bought_count is required")
    if body.quantity is not None:
        item.quantity = body.quantity
    if body.printing_ids is not None:
        card = await session.get(Card, item.card_id) if item.card_id is not None else None
        if card is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown card")
        shopping.set_editions(item, await _editions(session, card, body.printing_ids))
    if body.bought_count is not None:
        item.bought = body.bought_count
    elif body.bought is not None:
        item.bought = item.quantity if body.bought else 0
    item.bought = min(max(item.bought, 0), item.quantity)
    await session.commit()
    return await shopping_detail(session, user, list_id)


@router.delete("/{list_id}/items/{item_id}")
async def delete_shopping_item(
    list_id: int, item_id: int, user: CurrentUser, session: SessionDep
) -> ShoppingListDetailOut:
    await session.delete(await _item(session, user, list_id, item_id))
    await session.commit()
    return await shopping_detail(session, user, list_id)


@router.delete("/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shopping_list(list_id: int, user: CurrentUser, session: SessionDep) -> None:
    found = await session.scalar(
        select(ShoppingList).where(ShoppingList.id == list_id, ShoppingList.user_id == user.id)
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shopping list not found")
    await session.delete(found)
    await session.commit()


SHOPPING_TYPES = {
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "pdf": "application/pdf",
}


def filename(name: str, extension: str) -> str:
    """A file name from a list's name ("Burn.txt")."""
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()
    return f"{safe or 'shopping'}.{extension}"


@router.get(
    "/{list_id}/download",
    response_class=Response,
    responses={200: {"content": {t: {} for t in SHOPPING_TYPES.values()}}},
)
async def download_shopping_list(
    list_id: int,
    user: CurrentUser,
    session: SessionDep,
    format: Literal["txt", "md", "pdf"] = "txt",
) -> Response:
    """The list as a check list file in the user's language: its editions, copies and
    ticks, one box per copy."""
    found = await _load(session, user, list_id)
    lines = [shopping.item_line(i) for i in found.items]
    render = {"txt": shopping.to_txt, "md": shopping.to_md, "pdf": shopping.to_pdf}[format]
    content = render(found.name, lines, user.language, date.today())
    return Response(
        content,
        media_type=SHOPPING_TYPES[format],
        headers={
            "Content-Disposition": f'attachment; filename="{filename(found.name, format)}"',
            "Cache-Control": "private, no-store",
        },
    )


class ShoppingSyncOut(BaseModel):
    """Create list / Update list of a deck or a followed set: "created" or "updated"
    (`list` given), "deleted" (nothing missing any more, the list is gone) or "nothing"
    (nothing missing, no list made)."""

    status: shopping.SyncStatus
    list: ShoppingListDetailOut | None


async def sync_out(
    session: SessionDep, user: User, state: shopping.SyncStatus, found: ShoppingList | None
) -> ShoppingSyncOut:
    return ShoppingSyncOut(
        status=state,
        list=await shopping_detail(session, user, found.id) if found is not None else None,
    )
