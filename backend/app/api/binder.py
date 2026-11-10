"""Binder module (`app.modules`): sets a user follows, checked off from the collection.

Progress is read from the collection, so copies added anywhere (scan, import, card
page) count; the web adds and removes copies with `/api/collection/adjust`."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.catalog import (
    SetOut,
    _set_out,
    load_names,
    number_sort_key,
    orientation,
    rarity_code,
    set_languages,
    show_printing,
)
from app.api.deps import SessionDep
from app.models import BinderSet, CardSet, CollectionItem, Printing
from app.modules import require_module
from app.services import binder

router = APIRouter(prefix="/binder", tags=["binder"])

BinderUser = require_module("binder")


class BinderOut(BaseModel):
    id: int
    game_id: str
    set: SetOut
    # Only copies in this language / finish count; None: any.
    language: str | None
    finish: str | None
    # Printings of the set owned (matching copies), and printings of the set.
    owned: int
    total: int
    created_at: datetime


class BinderIn(BaseModel):
    set_id: int
    language: str | None = None
    finish: str | None = None


class BinderUpdateIn(BaseModel):
    """Fields left out are not changed; null: any language / finish."""

    language: str | None = None
    finish: str | None = None


class BinderItemOut(BaseModel):
    """A collection item counting for the binder (to remove a copy)."""

    id: int
    finish: str
    condition: str
    language: str
    quantity: int


class BinderRowOut(BaseModel):
    printing_id: int
    card_id: int
    collector_number: str | None
    name: str
    translation: str | None = None
    rarity: str | None
    rarity_code: str | None = None
    image: str | None
    orientation: str = "portrait"
    finishes: list[str]
    languages: list[str]
    # Matching copies owned (0: missing), and the items holding them.
    quantity: int
    items: list[BinderItemOut]


class BinderDetailOut(BaseModel):
    binder: BinderOut
    rows: list[BinderRowOut]


async def _binders_out(
    session: SessionDep, user_id: int, binders: list[BinderSet]
) -> list[BinderOut]:
    counts = await binder.progress(session, user_id, binders)
    languages = await set_languages(session, (b.set_id for b in binders))
    return [
        BinderOut(
            id=b.id,
            game_id=b.set.game_id,
            set=_set_out(b.set, languages),
            language=b.language,
            finish=b.finish,
            owned=counts[b.id][0],
            total=counts[b.id][1],
            created_at=b.created_at,
        )
        for b in binders
    ]


async def _own(session: SessionDep, user_id: int, binder_id: int) -> BinderSet:
    found = await session.scalar(
        select(BinderSet)
        .where(BinderSet.id == binder_id, BinderSet.user_id == user_id)
        .options(selectinload(BinderSet.set))
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Binder not found")
    return found


async def _check_filters(
    session: SessionDep, set_id: int, language: str | None, finish: str | None
) -> None:
    """The language and finish must be some printing's of the set."""
    if language is not None:
        known = (await set_languages(session, [set_id])).get(set_id, set())
        if language not in known:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"No printing of this set in '{language}'"
            )
    if finish is not None:
        finishes = set(
            await session.scalars(
                select(func.unnest(Printing.finishes)).where(Printing.set_id == set_id).distinct()
            )
        )
        if finish not in finishes:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"No printing of this set in '{finish}'"
            )


@router.get("")
async def list_binders(user: BinderUser, session: SessionDep) -> list[BinderOut]:
    """Followed sets, newest set first, with their progress."""
    binders = await session.scalars(
        select(BinderSet)
        .join(CardSet)
        .where(BinderSet.user_id == user.id)
        .order_by(CardSet.release_date.desc().nulls_last(), CardSet.name, BinderSet.id)
        .options(selectinload(BinderSet.set))
    )
    return await _binders_out(session, user.id, list(binders))


@router.post("", status_code=status.HTTP_201_CREATED)
async def follow_set(body: BinderIn, user: BinderUser, session: SessionDep) -> BinderOut:
    """Follow a set (once per set)."""
    if await session.get(CardSet, body.set_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Set not found")
    await _check_filters(session, body.set_id, body.language, body.finish)
    added = BinderSet(
        user_id=user.id, set_id=body.set_id, language=body.language, finish=body.finish
    )
    session.add(added)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This set is already followed") from exc
    return (await _binders_out(session, user.id, [await _own(session, user.id, added.id)]))[0]


@router.patch("/{binder_id}")
async def update_binder(
    binder_id: int, body: BinderUpdateIn, user: BinderUser, session: SessionDep
) -> BinderOut:
    found = await _own(session, user.id, binder_id)
    fields = body.model_dump(exclude_unset=True)
    await _check_filters(session, found.set_id, fields.get("language"), fields.get("finish"))
    for key, value in fields.items():
        setattr(found, key, value)
    await session.commit()
    return (await _binders_out(session, user.id, [found]))[0]


@router.delete("/{binder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow_set(binder_id: int, user: BinderUser, session: SessionDep) -> None:
    """Stop following a set (the collection is not changed)."""
    await session.delete(await _own(session, user.id, binder_id))
    await session.commit()


@router.get("/{binder_id}")
async def binder_detail(binder_id: int, user: BinderUser, session: SessionDep) -> BinderDetailOut:
    """Every printing of the set in collector number order, with the matching copies."""
    found = await _own(session, user.id, binder_id)
    printings = list(
        await session.scalars(
            select(Printing)
            .where(Printing.set_id == found.set_id)
            .order_by(number_sort_key(Printing.collector_number), Printing.id)
            .options(selectinload(Printing.set), selectinload(Printing.card))
        )
    )
    items: dict[int, list[CollectionItem]] = {}
    owned = await session.scalars(
        select(CollectionItem)
        .join(Printing)
        .where(
            CollectionItem.user_id == user.id,
            Printing.set_id == found.set_id,
            binder.counts(found.language, found.finish),
        )
        .order_by(CollectionItem.id)
    )
    for item in owned:
        items.setdefault(item.printing_id, []).append(item)
    card_names, printing_names = await load_names(session, {p.card_id for p in printings})
    # Shown in the binder's language when it has one.
    lang = found.language or user.language
    rows = []
    for printing in printings:
        shown, image = show_printing(printing, card_names, printing_names, lang, printing.card.name)
        held = items.get(printing.id, [])
        rows.append(
            BinderRowOut(
                printing_id=printing.id,
                card_id=printing.card_id,
                collector_number=printing.collector_number,
                name=shown.name,
                translation=shown.translation,
                rarity=printing.rarity,
                rarity_code=rarity_code(printing),
                image=image,
                orientation=orientation(printing),
                finishes=printing.finishes,
                languages=printing.languages,
                quantity=sum(i.quantity for i in held),
                items=[
                    BinderItemOut(
                        id=i.id,
                        finish=i.finish,
                        condition=i.condition,
                        language=i.language,
                        quantity=i.quantity,
                    )
                    for i in held
                ],
            )
        )
    return BinderDetailOut(binder=(await _binders_out(session, user.id, [found]))[0], rows=rows)
