import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
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
from app.core.http import http_client, shared_http_client
from app.games.base import FilterDef, rarity_of, registry
from app.models import (
    Card,
    CardName,
    CardSet,
    CollectionItem,
    PriceSnapshot,
    Printing,
    User,
)
from app.prices.base import price_sources, shown_sources
from app.services import collection, images, refresh
from app.services.display import ShownName, card_is_latin, latest_lang, pick_image, pick_name
from app.services.identify import number_matches
from app.services.names import display_name
from app.services.scripts import printing_is_latin, printing_lang

log = logging.getLogger(__name__)
router = APIRouter(tags=["catalog"])

SORT_BY_SHOWN_NAME_MAX = 5000


class SetOut(BaseModel):
    id: int
    code: str
    name: str
    lang: str | None
    # The one language of a regional set's printings (Korean-only set): shown as a flag.
    # None when printed in several languages (one Japanese set also printed in Korean...).
    exclusive_lang: str | None = None
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
    # The game's rarity (`GameOut.rarities`), for its pictogram; None when unknown.
    rarity_code: str | None = None
    artist: str | None
    finishes: list[str]
    languages: list[str]
    image: str | None
    # Back of double-faced cards (local copy).
    back_image: str | None = None
    # "landscape": the picture is wider than tall (Riftbound battlefields), shown turned.
    orientation: str = "portrait"
    # Shown name: in the reader's language, or for printings of non-Latin sets in the
    # set's language with a Latin `translation` ("ビードル (Aspicot)").
    name: str = ""
    translation: str | None = None
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
    # Latin name next to the name of cards printed only in non-Latin scripts.
    translation: str | None = None
    # Printing shown for the card, as in the catalog: the card's page opens on it.
    default_printing_id: int | None = None
    # The card's name in every language any of its printings is known in.
    names: dict[str, str] = {}
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
    # Latin name next to the name of cards printed only in non-Latin scripts.
    translation: str | None = None
    colors: list[str]
    printing_count: int
    image: str | None
    # Printing whose image is shown: the card's page opens on it.
    printing_id: int | None = None
    # Back face of that printing (double-faced cards), served like `image`.
    back_image: str | None = None
    # Of that printing: set, number, rarity and picture orientation.
    set: SetOut | None = None
    collector_number: str | None = None
    rarity: str | None = None
    rarity_code: str | None = None
    orientation: str = "portrait"
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


def number_sort_key(number: Any) -> Any:
    """Collector numbers in printed order: "2" < "10" < "TG05"; letters before the first
    digits group the specials ("SV001"), the rest of the text breaks ties ("12a")."""
    digits = func.coalesce(func.substring(number, r"\d+"), "")
    return func.concat(func.regexp_replace(number, r"\d.*$", ""), func.lpad(digits, 8, "0"), number)


def rarity_code(printing: Printing) -> str | None:
    """Code of the game's rarity the printing has (set loaded)."""
    rarity = rarity_of(printing.set.game_id, printing.rarity)
    return rarity.code if rarity else None


def orientation(printing: Printing) -> str:
    return "landscape" if printing.attributes.get("orientation") == "landscape" else "portrait"


def back_image_link(printing: Printing) -> str | None:
    """Local link to the back face of a double-faced printing."""
    if not printing.attributes.get("back_image_url"):
        return None
    return f"/api/printings/{printing.id}/image?face=back"


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
    # Collector numbers as stored for a printed code ("BETB-FR024" -> "BETB-EN024").
    numbers: list[str] = field(default_factory=list)


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
    if len(tokens) == 1:
        # A whole printed code ("BETB-FR024"), read by the game.
        for gid, provider in registry().items():
            lookup = getattr(provider, "code_lookup", None)
            found = lookup(tokens[0]) if lookup and (game is None or gid == game) else None
            if not found:
                continue
            set_codes, numbers = found
            set_ids = list(
                await session.scalars(
                    select(CardSet.id).where(
                        CardSet.game_id == gid,
                        func.lower(CardSet.code).in_([c.lower() for c in set_codes]),
                    )
                )
            )
            if set_ids:
                return CodeQuery(named_game, set_ids, None, numbers)
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
    """Image URL in `lang` (with fallbacks, see `images`)."""
    if images.has_image(printing):
        return f"/api/printings/{printing.id}/image?lang={lang}"
    return None


Names = dict[int, dict[str, str]]


async def load_names(session: SessionDep, card_ids: Iterable[int]) -> tuple[Names, Names]:
    """Names per language of the cards, and of their printings (printed names)."""
    rows = await session.execute(
        select(CardName.card_id, CardName.printing_id, CardName.lang, CardName.name).where(
            CardName.card_id.in_(set(card_ids))
        )
    )
    card_names: Names = {}
    printing_names: Names = {}
    for card_id, printing_id, lang, name in rows:
        if printing_id is None:
            card_names.setdefault(card_id, {})[lang] = name
        else:
            printing_names.setdefault(printing_id, {})[lang] = name
    return card_names, printing_names


def show_printing(
    printing: Printing,
    card_names: Names,
    printing_names: Names,
    ui_lang: str,
    default_name: str = "",
) -> tuple[ShownName, str | None]:
    """Name and image link of a printing (set loaded), shown as printed in its own set
    (see `display`). `default_name` when no name is known."""
    names = {**card_names.get(printing.card_id, {}), **printing_names.get(printing.id, {})}
    latin, set_lang = printing_is_latin(printing), printing_lang(printing)
    picked = pick_image([printing], ui_lang, latin, set_lang)
    return (
        pick_name(names, ui_lang, latin, set_lang, default=default_name),
        image_link(printing, picked[1]) if picked else None,
    )


@dataclass
class ShownCard:
    name: ShownName
    # Printing whose image shows the card (None: no printing has an image).
    printing: Printing | None
    image: str | None


def show_card(
    card: Card,
    card_names: Names,
    printing_names: Names,
    ui_lang: str,
    shown_sets: set[int] | None = None,
    default_name: str | None = None,
) -> ShownCard:
    """Image and name of a card (printings and their sets loaded), see `display`. With
    `shown_sets` (set filter), the card is shown as printed in those sets."""
    printings = [p for p in card.printings if p.set_id in (shown_sets or ())] or card.printings
    latin = card_is_latin(printings)
    set_lang = latest_lang(printings)
    picked = pick_image(printings, ui_lang, latin, set_lang)
    if picked is None and len(printings) < len(card.printings):
        picked = pick_image(card.printings, ui_lang, latin, set_lang)
    printing, lang = picked or (None, None)
    # Card names win over printed names, the shown printing's over the others'.
    names: dict[str, str] = {}
    for p in card.printings:
        if p is not printing:
            names.update(printing_names.get(p.id, {}))
    if printing is not None:
        names.update(printing_names.get(printing.id, {}))
    names.update(card_names.get(card.id, {}))
    return ShownCard(
        name=pick_name(names, ui_lang, latin, set_lang, default=default_name or card.name),
        printing=printing,
        image=image_link(printing, lang) if printing and lang else None,
    )


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


SetLanguages = dict[int, set[str]]


async def set_languages(session: SessionDep, set_ids: Iterable[int]) -> SetLanguages:
    """Languages of the printings of each set."""
    wanted = set(set_ids)
    if not wanted:
        return {}
    lang = func.unnest(Printing.languages).label("lang")
    rows = await session.execute(
        select(Printing.set_id, lang).where(Printing.set_id.in_(wanted)).distinct()
    )
    found: SetLanguages = {}
    for set_id, code in rows:
        found.setdefault(set_id, set()).add(code)
    return found


def exclusive_lang(card_set: CardSet, languages: SetLanguages) -> str | None:
    """Language a regional set is printed in alone (international sets: never)."""
    if card_set.lang is None:
        return None
    langs = languages.get(card_set.id, set())
    if not langs:
        return card_set.lang
    return next(iter(langs)) if len(langs) == 1 else None


def _set_out(card_set: CardSet, languages: SetLanguages | None = None) -> SetOut:
    return SetOut(
        id=card_set.id,
        code=card_set.code,
        name=card_set.name,
        lang=card_set.lang,
        exclusive_lang=exclusive_lang(card_set, languages or {}),
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
    path = await images.cached_asset(
        shared_http_client(), card_set.icon_url, images.set_icon_stem(card_set)
    )
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
    sets = list(sets)
    languages = await set_languages(session, (s.id for s in sets))
    return [_set_out(s, languages) for s in sets]


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
    color_mode: Literal["include", "exact"] = "include",
    sort: Literal["relevance", "name", "number"] = "relevance",
    order: Literal["asc", "desc"] = "asc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CardPageOut:
    """Search cards by name in any language (substring match, case and accents
    ignored), set and colors. Exact name matches come first, then names starting with
    `q`. Without `game`, only the games chosen in the user's settings are searched.

    `attr=<filter key>:<value>` (repeatable, all must match) uses the game's advanced
    filters (GameOut.filters); it needs `game`.

    `color_mode=exact`: cards of exactly the chosen colors (default: at least them).
    `sort=name` orders by shown name, `sort=number` by collector number in `set_id`
    (ignored without a set); `order` gives the direction."""
    # Cards without printings cannot be collected (left over by older catalog syncs).
    name = display_name(user.language)
    query = select(Card).where(exists().where(Printing.card_id == Card.id))
    ordering: list[Any] = []
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
        if code.numbers:
            in_set = in_set.where(Printing.collector_number.in_(code.numbers))
        named = select(CardName.card_id).where(name_matches(q))
        query = query.where(or_(Card.id.in_(in_set), Card.id.in_(named)))
        ordering.insert(0, case((Card.id.in_(in_set), 0), else_=1))
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
        ordering.insert(0, rank)
    if set_id is not None:
        query = query.where(exists().where(Printing.card_id == Card.id, Printing.set_id == set_id))
    if color:
        query = query.where(Card.colors.contains(color))
        if color_mode == "exact":
            query = query.where(Card.colors.contained_by(color))
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
    direction = (lambda c: c.desc()) if order == "desc" else (lambda c: c.asc())
    # Sorting by the shown name costs a name lookup per card: whole catalogs (tens of
    # thousands of cards) are sorted by their Latin name instead (indexed), cards known
    # only by non-Latin names last in either direction.
    if (total or 0) <= SORT_BY_SHOWN_NAME_MAX:
        by_name = [direction(name)]
    else:
        by_name = [direction(Card.sort_name).nulls_last(), direction(Card.name)]
    if sort == "number" and set_id is not None:
        number = (
            select(func.min(number_sort_key(Printing.collector_number)))
            .where(Printing.card_id == Card.id, Printing.set_id == set_id)
            .scalar_subquery()
        )
        ordering = [direction(number), *by_name, direction(Card.id)]
    elif sort == "name":
        ordering = [*by_name, direction(Card.id)]
    else:
        ordering += [*by_name, Card.id]
    rows = (
        await session.execute(
            query.add_columns(name)
            .order_by(*ordering)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .options(selectinload(Card.printings).selectinload(Printing.set))
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
    # Cards are shown as printed in the chosen set (set filter or code search).
    shown_sets = {set_id} if set_id is not None else set(code.set_ids if code else ())
    card_names, printing_names = await load_names(session, (c.id for c in cards))
    shown_cards = [
        (
            card,
            show_card(card, card_names, printing_names, user.language, shown_sets, names[card.id]),
        )
        for card in cards
    ]
    languages = await set_languages(
        session, (shown.printing.set_id for _, shown in shown_cards if shown.printing)
    )
    items = []
    for card, shown in shown_cards:
        items.append(
            CardSummaryOut(
                id=card.id,
                game_id=card.game_id,
                name=shown.name.name,
                translation=shown.name.translation,
                colors=card.colors,
                printing_count=len(card.printings),
                image=shown.image,
                printing_id=shown.printing.id if shown.printing else None,
                back_image=back_image_link(shown.printing) if shown.printing else None,
                set=_set_out(shown.printing.set, languages) if shown.printing else None,
                collector_number=shown.printing.collector_number if shown.printing else None,
                rarity=shown.printing.rarity if shown.printing else None,
                rarity_code=rarity_code(shown.printing) if shown.printing else None,
                orientation=orientation(shown.printing) if shown.printing else "portrait",
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
    card_names, printing_names = await load_names(session, [card.id])
    shown = show_card(card, card_names, printing_names, user.language, default_name=name)
    default = shown.printing or (printings[0] if printings else None)
    # Card names win over printed names (a printing's own spelling).
    all_names: dict[str, str] = {}
    for p in printings:
        for lang, printed in printing_names.get(p.id, {}).items():
            all_names.setdefault(lang, printed)
    all_names.update(card_names.get(card.id, {}))
    return CardOut(
        id=card.id,
        game_id=card.game_id,
        name=shown.name.name,
        translation=shown.name.translation,
        default_printing_id=default.id if default else None,
        names=all_names,
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
    card_names, printing_names = await load_names(session, {p.card_id for p in printings})
    games = {p.set.game_id for p in printings}
    prices: dict[int, list[PriceOut]] = {}
    for game_id in sorted(games):
        ids = [p.id for p in printings if p.set.game_id == game_id]
        # The user's sources, main one first.
        for source in shown_sources(game_id, user.price_sources):
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
    languages = await set_languages(session, (p.set_id for p in printings))
    described = []
    for p in printings:
        names = {**card_names.get(p.card_id, {}), **printing_names.get(p.id, {})}
        shown, image = show_printing(p, card_names, printing_names, user.language)
        described.append(
            PrintingOut(
                id=p.id,
                set=_set_out(p.set, languages),
                collector_number=p.collector_number,
                rarity=p.rarity,
                rarity_code=rarity_code(p),
                artist=p.artist,
                finishes=p.finishes,
                languages=p.languages,
                image=image,
                back_image=back_image_link(p),
                orientation=orientation(p),
                name=shown.name,
                translation=shown.translation,
                names=names,
                attributes=p.attributes,
                cardmarket_id=_int_or_none(_market_ids(p).get("cardmarket")),
                links=_links(p, user.language, user.price_sources),
                prices=prices.get(p.id, []),
                owned=owned.get(p.id, []),
            )
        )
    return described


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


def _links(printing: Printing, lang: str, wanted: list[str]) -> list[LinkOut]:
    """Market pages of the printing, for the user's sources."""
    shown = {s.id for s in shown_sources(printing.set.game_id, wanted)}
    links = []
    for source_id, market_id in _market_ids(printing).items():
        source = price_sources().get(source_id) if source_id in shown else None
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
    user: CurrentUser,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=3650)] = 365,
) -> list[PriceHistoryOut]:
    """Price snapshots from the user's sources, oldest first. Full history exists for
    printings in a collection."""
    game_id = await session.scalar(
        select(CardSet.game_id).join(Printing).where(Printing.id == printing_id)
    )
    if game_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Printing not found")
    shown = [s.id for s in shown_sources(game_id, user.price_sources)]
    rows = await session.scalars(
        select(PriceSnapshot)
        .where(
            PriceSnapshot.printing_id == printing_id,
            PriceSnapshot.source.in_(shown),
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
    size: Literal["full", "thumb"] = "full",
) -> FileResponse:
    """Card image in `lang` (default: the user's language), else English, else
    Japanese, else any language there is. `face=back`: the back of double-faced cards.
    `size=thumb`: a small copy for lists and grids."""
    printing = await session.get(Printing, printing_id)
    if printing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Printing not found")
    if face == "back":
        card_set = await session.get(CardSet, printing.set_id)
        game_id = card_set.game_id if card_set else ""
        path = await images.cached_asset(
            shared_http_client(),
            printing.attributes.get("back_image_url"),
            images.back_stem(game_id, printing),
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
        path = await images.get_or_fetch(session, shared_http_client(), printing, wanted)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No image for this printing")
    if size == "thumb":
        path = await images.thumbnail(path)
    return FileResponse(path, headers={"Cache-Control": "private, max-age=604800"})
