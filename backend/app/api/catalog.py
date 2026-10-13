from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import ColumnElement, case, exists, func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, SessionDep
from app.core.http import http_client
from app.models import (
    Card,
    CardName,
    CardSet,
    CollectionItem,
    PriceSnapshot,
    Printing,
    User,
)
from app.services import collection, images

router = APIRouter(tags=["catalog"])


class SetOut(BaseModel):
    id: int
    code: str
    name: str
    lang: str | None
    release_date: date | None
    total: int | None
    icon_url: str | None


class OwnedOut(BaseModel):
    item_id: int
    finish: str
    condition: str
    language: str
    quantity: int


class PriceOut(BaseModel):
    finish: str
    trend: Decimal
    # Lowest Cardmarket offer, when the price source gives it.
    low: Decimal | None
    date: date


class PrintingOut(BaseModel):
    id: int
    set: SetOut
    collector_number: str | None
    rarity: str | None
    artist: str | None
    finishes: list[str]
    languages: list[str]
    image: str | None
    names: dict[str, str]
    attributes: dict[str, Any]
    # Cardmarket product, for a link to its page (see GameOut.cardmarket).
    cardmarket_id: int | None
    # Latest API price per finish and the current user's copies.
    prices: list[PriceOut]
    owned: list[OwnedOut]


class CardOut(BaseModel):
    id: int
    game_id: str
    name: str
    colors: list[str]
    attributes: dict[str, Any]
    printings: list[PrintingOut]


class CardSummaryOut(BaseModel):
    id: int
    game_id: str
    name: str
    colors: list[str]
    printing_count: int
    image: str | None
    # Cheapest and most expensive printing (latest trend price of any finish).
    price_min: Decimal | None
    price_max: Decimal | None


class CardPageOut(BaseModel):
    items: list[CardSummaryOut]
    total: int
    page: int
    page_size: int


def _escape_like(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _search_text(q: str) -> ColumnElement[str]:
    """`q` normalized like `CardName.search_name` (lower case, no accents)."""
    return func.lower(func.f_unaccent(_escape_like(q)))


def name_matches(q: str) -> ColumnElement[bool]:
    """Card name contains `q`, ignoring case and accents ("foret" finds "Forêt")."""
    return CardName.search_name.like("%" + _search_text(q) + "%")


def image_link(printing: Printing, lang: str) -> str | None:
    """Image URL in the user's language (with fallbacks, see `images`)."""
    if images.has_image(printing):
        return f"/api/printings/{printing.id}/image?lang={lang}"
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _set_out(card_set: CardSet) -> SetOut:
    return SetOut.model_validate(card_set, from_attributes=True)


@router.get("/games/{game_id}/sets")
async def list_sets(game_id: str, _: CurrentUser, session: SessionDep) -> list[SetOut]:
    sets = await session.scalars(
        select(CardSet)
        .where(CardSet.game_id == game_id)
        .order_by(CardSet.release_date.desc().nulls_last(), CardSet.name)
    )
    return [_set_out(s) for s in sets]


@router.get("/cards")
async def search_cards(
    user: CurrentUser,
    session: SessionDep,
    game: str | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    set_id: int | None = None,
    color: Annotated[list[str] | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CardPageOut:
    """Search cards by name in any language (substring match, case and accents
    ignored), set and colors. Exact name matches come first, then names starting with
    `q`. Without `game`, only the games chosen in the user's settings are searched."""
    query = select(Card)
    order: list[Any] = [Card.name, Card.id]
    if game:
        query = query.where(Card.game_id == game)
    elif user.catalog_games is not None:
        query = query.where(Card.game_id.in_(user.catalog_games))
    if q:
        query = query.where(exists().where(CardName.card_id == Card.id, name_matches(q)))
        text = _search_text(q)
        rank = (
            select(
                func.min(
                    case(
                        (CardName.search_name == func.lower(func.f_unaccent(q)), 0),
                        (CardName.search_name.like(text + "%"), 1),
                        else_=2,
                    )
                )
            )
            .where(CardName.card_id == Card.id)
            .scalar_subquery()
        )
        order.insert(0, rank)
    if set_id is not None:
        query = query.where(exists().where(Printing.card_id == Card.id, Printing.set_id == set_id))
    if color:
        query = query.where(Card.colors.contains(color))

    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    cards = (
        await session.scalars(
            query.order_by(*order)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .options(selectinload(Card.printings))
        )
    ).all()
    latest = await collection.latest_prices(session, (p.id for c in cards for p in c.printings))
    card_prices: dict[int, list[Decimal]] = {}
    by_printing = {p.id: c.id for c in cards for p in c.printings}
    for (printing_id, _), point in latest.items():
        card_prices.setdefault(by_printing[printing_id], []).append(point.trend)
    items = []
    for card in cards:
        # A printing that has the user's language, then one already cached.
        printings = sorted(
            card.printings,
            key=lambda p: (user.language not in p.image_urls, not any(p.image_paths.values())),
        )
        items.append(
            CardSummaryOut(
                id=card.id,
                game_id=card.game_id,
                name=card.name,
                colors=card.colors,
                printing_count=len(printings),
                image=next(
                    (link for p in printings if (link := image_link(p, user.language))), None
                ),
                price_min=min(card_prices.get(card.id, []), default=None),
                price_max=max(card_prices.get(card.id, []), default=None),
            )
        )
    return CardPageOut(items=items, total=total or 0, page=page, page_size=page_size)


@router.get("/cards/{card_id}")
async def get_card(card_id: int, user: CurrentUser, session: SessionDep) -> CardOut:
    card = await session.scalar(
        select(Card)
        .where(Card.id == card_id)
        .options(selectinload(Card.printings).selectinload(Printing.set))
    )
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found")
    printings = sorted(
        card.printings,
        key=lambda p: (p.set.release_date or date.min, p.collector_number or ""),
        reverse=True,
    )
    described = await describe_printings(session, user, printings)
    # Printings the user owns first, newest first within each group (stable sort).
    described.sort(key=lambda p: not p.owned)
    return CardOut(
        id=card.id,
        game_id=card.game_id,
        name=card.name,
        colors=card.colors,
        attributes=card.attributes,
        printings=described,
    )


async def describe_printings(
    session: SessionDep, user: User, printings: list[Printing]
) -> list[PrintingOut]:
    """Printings (with `set` loaded) with localized names, latest prices and the user's
    copies, in the given order. Images are in the user's language when available."""
    user_id = user.id
    printing_ids = [p.id for p in printings]
    card_ids = {p.card_id for p in printings}
    rows = await session.execute(
        select(CardName.card_id, CardName.printing_id, CardName.lang, CardName.name).where(
            CardName.card_id.in_(card_ids)
        )
    )
    card_names: dict[int, dict[str, str]] = {}
    printing_names: dict[int, dict[str, str]] = {}
    for card_id, printing_id, lang, name in rows:
        if printing_id is None:
            card_names.setdefault(card_id, {})[lang] = name
        else:
            printing_names.setdefault(printing_id, {})[lang] = name
    latest = await collection.latest_prices(session, printing_ids)
    prices: dict[int, list[PriceOut]] = {}
    for (printing_id, finish), point in sorted(latest.items()):
        prices.setdefault(printing_id, []).append(
            PriceOut(finish=finish, trend=point.trend, low=point.low, date=point.date)
        )
    owned: dict[int, list[OwnedOut]] = {}
    items = await session.scalars(
        select(CollectionItem)
        .where(
            CollectionItem.user_id == user_id,
            CollectionItem.printing_id.in_(printing_ids),
            CollectionItem.quantity > 0,
        )
        .order_by(CollectionItem.id)
    )
    for item in items:
        owned.setdefault(item.printing_id, []).append(
            OwnedOut(
                item_id=item.id,
                finish=item.finish,
                condition=item.condition,
                language=item.language,
                quantity=item.quantity,
            )
        )
    return [
        PrintingOut(
            id=p.id,
            set=_set_out(p.set),
            collector_number=p.collector_number,
            rarity=p.rarity,
            artist=p.artist,
            finishes=p.finishes,
            languages=p.languages,
            image=image_link(p, user.language),
            names={**card_names.get(p.card_id, {}), **printing_names.get(p.id, {})},
            attributes=p.attributes,
            cardmarket_id=_int_or_none(p.attributes.get("cardmarket_id")),
            prices=prices.get(p.id, []),
            owned=owned.get(p.id, []),
        )
        for p in printings
    ]


class PriceHistoryOut(BaseModel):
    date: date
    finish: str
    source: str
    currency: str
    trend: Decimal | None
    low: Decimal | None
    avg: Decimal | None


@router.get("/printings/{printing_id}/prices")
async def price_history(
    printing_id: int,
    _: CurrentUser,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=3650)] = 365,
) -> list[PriceHistoryOut]:
    """Price snapshots, oldest first. Full history exists for printings in a collection."""
    if await session.get(Printing, printing_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Printing not found")
    rows = await session.scalars(
        select(PriceSnapshot)
        .where(
            PriceSnapshot.printing_id == printing_id,
            PriceSnapshot.date > date.today() - timedelta(days=days),
        )
        .order_by(PriceSnapshot.date, PriceSnapshot.finish)
    )
    return [PriceHistoryOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/printings/{printing_id}/image")
async def printing_image(
    printing_id: int,
    user: CurrentUser,
    session: SessionDep,
    lang: Annotated[str | None, Query(max_length=8)] = None,
) -> FileResponse:
    """Card image in `lang` (default: the user's language), else English, else
    Japanese, else any language there is."""
    printing = await session.get(Printing, printing_id)
    if printing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Printing not found")
    wanted = lang or user.language
    languages = images.image_languages(printing, wanted)
    # Fast path: the best language is cached. Otherwise try to download it (or the next
    # best one), keeping cached fallbacks for when downloads fail.
    path = images.cached_file(printing, languages[0]) if languages else None
    if path is None:
        async with http_client(timeout=20) as http:
            path = await images.get_or_fetch(session, http, printing, wanted)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No image for this printing")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=604800"})
