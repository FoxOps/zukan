import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import ColumnElement, case, exists, func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, SessionDep
from app.core.db import get_sessionmaker
from app.core.http import http_client
from app.games.base import FilterDef, registry
from app.models import (
    Card,
    CardName,
    CardSet,
    CollectionItem,
    PriceSnapshot,
    Printing,
    User,
)
from app.prices.base import game_sources, price_sources
from app.services import collection, images, refresh
from app.services.identify import number_matches
from app.services.names import display_name

log = logging.getLogger(__name__)
router = APIRouter(tags=["catalog"])

SORT_BY_SHOWN_NAME_MAX = 5000


class SetOut(BaseModel):
    id: int
    code: str
    name: str
    lang: str | None
    release_date: date | None
    total: int | None
    # Set symbol, served from the local cache.
    icon: str | None


class OwnedOut(BaseModel):
    item_id: int
    finish: str
    condition: str
    language: str
    quantity: int


class PriceOut(BaseModel):
    finish: str
    # Price source id (GameOut.price_sources) and its currency.
    source: str
    currency: str
    trend: Decimal
    # Lowest offer, when the price source gives it.
    low: Decimal | None
    date: date


class LinkOut(BaseModel):
    # Price source id.
    source: str
    name: str
    url: str


class PrintingOut(BaseModel):
    id: int
    set: SetOut
    collector_number: str | None
    rarity: str | None
    artist: str | None
    finishes: list[str]
    languages: list[str]
    image: str | None
    # Back of double-faced cards (local copy).
    back_image: str | None = None
    names: dict[str, str]
    attributes: dict[str, Any]
    # Deprecated (app 0.3): use `links`.
    cardmarket_id: int | None
    # Product pages on the game's markets.
    links: list[LinkOut]
    # Latest price per source and finish (user's source first), the user's copies.
    prices: list[PriceOut]
    owned: list[OwnedOut]


class CardOut(BaseModel):
    id: int
    game_id: str
    name: str
    colors: list[str]
    attributes: dict[str, Any]
    printings: list[PrintingOut]
    # The card's data was incomplete or outdated: it is being fetched again; load the
    # card again in a few seconds.
    refreshing: bool = False


class CardSummaryOut(BaseModel):
    id: int
    game_id: str
    name: str
    colors: list[str]
    printing_count: int
    image: str | None
    # Cheapest and most expensive printing (latest trend price of any finish), from the
    # user's price source for this game, in `currency`.
    price_min: Decimal | None
    price_max: Decimal | None
    currency: str | None = None


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


@dataclass
class CodeQuery:
    """`q` read as "[game] set [number]", e.g. "pkm ssp 181", "j25 158", "sorcery ALP"."""

    game: str | None
    set_ids: list[int]
    number: str | None


async def parse_code_query(session: SessionDep, q: str, game: str | None) -> CodeQuery | None:
    """None when `q` is a plain name. `set_ids` is empty when only a game was named."""
    tokens = q.split()
    named_game = None
    if len(tokens) > 1 and game is None:
        named_game = next(
            (gid for gid, p in registry().items() if tokens[0].casefold() in _short_names(p)),
            None,
        )
        if named_game is not None:
            tokens = tokens[1:]
    game = game or named_game
    plain = CodeQuery(named_game, [], None) if named_game else None
    number = tokens[1].split("/")[0] if len(tokens) == 2 else None
    if len(tokens) > 2 or (number is not None and not any(ch.isdigit() for ch in number)):
        return plain
    code = tokens[0].casefold()
    codes = {code}
    for gid, provider in registry().items():
        if game is None or gid == game:
            for set_code, aliases in getattr(provider, "set_aliases", {}).items():
                if code in {a.casefold() for a in aliases}:
                    codes.add(set_code.casefold())
    query = select(CardSet.id).where(
        or_(func.lower(CardSet.code).in_(codes), func.lower(CardSet.external_id).in_(codes))
    )
    if game:
        query = query.where(CardSet.game_id == game)
    set_ids = list(await session.scalars(query))
    return CodeQuery(named_game, set_ids, number) if set_ids else plain


def _short_names(provider: Any) -> set[str]:
    return {provider.id, *(n.casefold() for n in getattr(provider, "short_names", []))}


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
    return SetOut(
        id=card_set.id,
        code=card_set.code,
        name=card_set.name,
        lang=card_set.lang,
        release_date=card_set.release_date,
        total=card_set.total,
        icon=f"/api/sets/{card_set.id}/icon" if card_set.icon_url else None,
    )


# Pictures are SVG or bitmaps from card data sources: never run anything they contain.
_ASSET_HEADERS = {
    "Cache-Control": "private, max-age=2592000",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
}


@router.get("/sets/{set_id}/icon")
async def set_icon(set_id: int, _: CurrentUser, session: SessionDep) -> FileResponse:
    card_set = await session.get(CardSet, set_id)
    if card_set is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Set not found")
    async with http_client(timeout=20) as http:
        path = await images.cached_asset(http, card_set.icon_url, images.set_icon_stem(card_set))
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No icon for this set")
    return FileResponse(path, headers=_ASSET_HEADERS)


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
    lang: Annotated[str | None, Query(max_length=8)] = None,
    attr: Annotated[list[str] | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CardPageOut:
    """Search cards by name in any language (substring match, case and accents
    ignored), set and colors. Exact name matches come first, then names starting with
    `q`. Without `game`, only the games chosen in the user's settings are searched.

    `attr=<filter key>:<value>` (repeatable, all must match) uses the game's advanced
    filters (GameOut.filters); it needs `game`."""
    # Cards without printings cannot be collected (left over by older catalog syncs).
    name = display_name(user.language)
    query = select(Card).where(exists().where(Printing.card_id == Card.id))
    order: list[Any] = []
    if game:
        query = query.where(Card.game_id == game)
    elif user.catalog_games is not None:
        query = query.where(Card.game_id.in_(user.catalog_games))
    code = await parse_code_query(session, q, game) if q else None
    if code is not None and code.game and not game:
        # "pkm lugia": the first word chose the game, the rest is a name.
        game = code.game
        query = query.where(Card.game_id == game)
        q = q.split(maxsplit=1)[1]
    if code is not None and code.set_ids:
        # Printings of that set (and number), or names matching the words anyway. Card id
        # sets (not correlated EXISTS under OR) keep the name and set indexes usable.
        in_set = select(Printing.card_id).where(Printing.set_id.in_(code.set_ids))
        if code.number:
            in_set = in_set.where(number_matches(Printing.collector_number, code.number))
        named = select(CardName.card_id).where(name_matches(q))
        query = query.where(or_(Card.id.in_(in_set), Card.id.in_(named)))
        order.insert(0, case((Card.id.in_(in_set), 0), else_=1))
    elif q:
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
    if attr:
        if not game:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "attr needs a game")
        filters = {f.key: f for f in getattr(registry()[game], "filters", [])}
        for item in attr:
            key, _, value = item.partition(":")
            if key not in filters or not value:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown filter {item!r}"
                )
            query = query.where(_filter_condition(filters[key], value))
    if lang:
        # Printed in that language.
        query = query.where(
            exists().where(Printing.card_id == Card.id, Printing.languages.contains([lang]))
        )

    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    # Sorting by the shown name costs a name lookup per card: whole catalogs (tens of
    # thousands of cards) are sorted by canonical name instead.
    order += [name if (total or 0) <= SORT_BY_SHOWN_NAME_MAX else Card.name, Card.id]
    rows = (
        await session.execute(
            query.add_columns(name)
            .order_by(*order)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .options(selectinload(Card.printings))
        )
    ).all()
    cards = [card for card, _ in rows]
    names = {card.id: card_name for card, card_name in rows}
    latest = await collection.user_prices(
        session, user.price_source, {p.id: c.game_id for c in cards for p in c.printings}
    )
    card_prices: dict[int, list[Decimal]] = {}
    by_printing = {p.id: c.id for c in cards for p in c.printings}
    for (printing_id, _), point in latest.items():
        card_prices.setdefault(by_printing[printing_id], []).append(point.trend)
    # Images show the chosen set (set filter or code search) when the card is in it.
    shown_sets = {set_id} if set_id is not None else set(code.set_ids if code else ())
    items = []
    for card in cards:
        # A printing of the chosen set, with the user's language, already cached.
        printings = sorted(
            card.printings,
            key=lambda p: (
                p.set_id not in shown_sets,
                user.language not in p.image_urls,
                not any(p.image_paths.values()),
            ),
        )
        items.append(
            CardSummaryOut(
                id=card.id,
                game_id=card.game_id,
                name=names[card.id],
                colors=card.colors,
                printing_count=len(printings),
                image=next(
                    (link for p in printings if (link := image_link(p, user.language))), None
                ),
                price_min=min(card_prices.get(card.id, []), default=None),
                price_max=max(card_prices.get(card.id, []), default=None),
                currency=_currency(card.game_id, user.price_source),
            )
        )
    return CardPageOut(items=items, total=total or 0, page=page, page_size=page_size)


async def _refresh_card(game_id: str, card_id: int) -> None:
    try:
        async with get_sessionmaker()() as session, http_client() as http:
            await refresh.refresh_cards(session, registry()[game_id], http, [card_id])
    except Exception:
        log.exception("Refresh of card %s failed", card_id)


async def _should_refresh(session: SessionDep, card: Card) -> bool:
    if not refresh.can_refresh(registry()[card.game_id]):
        return False
    attempted = card.refresh_attempted_at
    if attempted is not None and datetime.now(UTC) - attempted < refresh.RETRY_AFTER:
        return False
    return await refresh.is_stale(session, card)


@router.get("/cards/{card_id}")
async def get_card(
    card_id: int, user: CurrentUser, session: SessionDep, background: BackgroundTasks
) -> CardOut:
    row = (
        await session.execute(
            select(Card, display_name(user.language))
            .where(Card.id == card_id)
            .options(selectinload(Card.printings).selectinload(Printing.set))
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found")
    card, name = row
    # Stale or incomplete data: fetch the card again after answering.
    refreshing = await _should_refresh(session, card)
    if refreshing:
        background.add_task(_refresh_card, card.game_id, card.id)
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
        name=name,
        colors=card.colors,
        attributes=card.attributes,
        printings=described,
        refreshing=refreshing,
    )


@router.get("/cards/{card_id}/printings")
async def search_printings(
    card_id: int,
    user: CurrentUser,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[PrintingOut]:
    """The card's printings whose set name, set code, collector number or release year
    contain every word of `q` (case and accents ignored), newest first."""
    if await session.get(Card, card_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found")
    query = (
        select(Printing)
        .join(CardSet, Printing.set_id == CardSet.id)
        .where(Printing.card_id == card_id)
        .options(selectinload(Printing.set))
    )
    text = func.lower(
        func.f_unaccent(
            func.concat_ws(
                " ",
                CardSet.name,
                CardSet.code,
                Printing.collector_number,
                func.to_char(CardSet.release_date, "YYYY"),
            )
        )
    )
    for word in (q or "").split():
        query = query.where(text.like("%" + _search_text(word) + "%"))
    printings = list(
        await session.scalars(
            query.order_by(
                CardSet.release_date.desc().nulls_last(), Printing.collector_number
            ).limit(limit)
        )
    )
    return await describe_printings(session, user, printings)


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
    games = {p.set.game_id for p in printings}
    prices: dict[int, list[PriceOut]] = {}
    for game_id in sorted(games):
        ids = [p.id for p in printings if p.set.game_id == game_id]
        sources = game_sources(game_id)
        chosen = collection.pricing(game_id, user.price_source)
        # The user's source first.
        sources.sort(key=lambda source: chosen is None or source.id != chosen.source)
        for source in sources:
            latest = await collection.latest_prices(session, ids, source.id)
            for (printing_id, finish), point in sorted(latest.items()):
                prices.setdefault(printing_id, []).append(
                    PriceOut(
                        finish=finish,
                        source=source.id,
                        currency=point.currency,
                        trend=point.trend,
                        low=point.low,
                        date=point.date,
                    )
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
            back_image=f"/api/printings/{p.id}/image?face=back"
            if p.attributes.get("back_image_url")
            else None,
            names={**card_names.get(p.card_id, {}), **printing_names.get(p.id, {})},
            attributes=p.attributes,
            cardmarket_id=_int_or_none(_market_ids(p).get("cardmarket")),
            links=_links(p, user.language),
            prices=prices.get(p.id, []),
            owned=owned.get(p.id, []),
        )
        for p in printings
    ]


def _filter_condition(f: FilterDef, value: str) -> ColumnElement[bool]:
    if f.attribute is None:
        return exists().where(Printing.card_id == Card.id, Printing.rarity == value)
    # Containment works on string and list attributes and uses the GIN index.
    return or_(
        Card.attributes.contains({f.attribute: value}),
        Card.attributes.contains({f.attribute: [value]}),
    )


def _currency(game_id: str, wanted: str) -> str | None:
    chosen = collection.pricing(game_id, wanted)
    return chosen.currency if chosen else None


def _market_ids(printing: Printing) -> dict[str, Any]:
    return printing.attributes.get("market_ids") or {}


def _links(printing: Printing, lang: str) -> list[LinkOut]:
    links = []
    for source_id, market_id in _market_ids(printing).items():
        source = price_sources().get(source_id)
        url = source.link(printing.set.game_id, market_id, lang) if source else None
        if source and url:
            links.append(LinkOut(source=source.id, name=source.name, url=url))
    return links


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
    face: Literal["front", "back"] = "front",
) -> FileResponse:
    """Card image in `lang` (default: the user's language), else English, else
    Japanese, else any language there is. `face=back`: the back of double-faced cards."""
    printing = await session.get(Printing, printing_id)
    if printing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Printing not found")
    if face == "back":
        card_set = await session.get(CardSet, printing.set_id)
        game_id = card_set.game_id if card_set else ""
        async with http_client(timeout=20) as http:
            path = await images.cached_asset(
                http, printing.attributes.get("back_image_url"), images.back_stem(game_id, printing)
            )
        if path is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No back image for this printing")
        return FileResponse(path, headers=_ASSET_HEADERS)
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
