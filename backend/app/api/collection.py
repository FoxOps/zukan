from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import case, exists, func, select
from sqlalchemy.orm import contains_eager, selectinload

from app.api.catalog import (
    back_image_link,
    image_link,
    load_names,
    name_matches,
    number_sort_key,
    orientation,
    rarity_code,
    show_printing,
)
from app.api.deps import CurrentUser, SessionDep
from app.games.base import image_fallback, registry
from app.models import (
    Card,
    CardName,
    CardSet,
    CollectionItem,
    Condition,
    PriceSnapshot,
    Printing,
    StockTransaction,
)
from app.prices.base import price_sources
from app.services import collection, csv_io, images
from app.services.collection import StockError, Variant
from app.services.names import display_name

router = APIRouter(prefix="/collection", tags=["collection"])

Source = Literal["web", "scan"]
MAX_CSV_BYTES = 5 * 1024 * 1024


class ItemSetOut(BaseModel):
    id: int
    code: str
    name: str


class TrendOut(BaseModel):
    direction: Literal["up", "down", "flat"]
    # Relative change of the market price: 0.1 = +10 %.
    change: float


class TrendsOut(BaseModel):
    """Market price trend over 24 hours, 7 days and 30 days (None: not enough history)."""

    d1: TrendOut | None = None
    d7: TrendOut | None = None
    d30: TrendOut | None = None


class ItemOut(BaseModel):
    id: int
    printing_id: int
    card_id: int
    game_id: str
    # Named as printed in its set; Latin `translation` of non-Latin names.
    name: str
    translation: str | None = None
    colors: list[str]
    set: ItemSetOut
    collector_number: str | None
    rarity: str | None
    rarity_code: str | None = None
    image: str | None
    # Back face of double-faced printings.
    back_image: str | None = None
    orientation: str = "portrait"
    finish: str
    condition: str
    language: str
    quantity: int
    manual_price: Decimal | None
    market_price: Decimal | None
    # Of market and manual prices: the user's price source for this game.
    currency: str
    price_date: date | None
    unit_price: Decimal | None
    total: Decimal | None
    # Of the market price (a manual price does not change it).
    trends: TrendsOut = TrendsOut()
    notes: str | None
    updated_at: datetime


class ItemPageOut(BaseModel):
    items: list[ItemOut]
    total: int
    page: int
    page_size: int


class AdjustIn(BaseModel):
    printing_id: int
    finish: str
    condition: Condition = Condition.NM
    language: str
    delta: int = Field(ge=-1000, le=1000)
    source: Source = "web"


class AdjustOut(BaseModel):
    item: ItemOut
    transaction_id: int


class ItemUpdateIn(BaseModel):
    quantity: int | None = Field(default=None, ge=0, le=100_000)
    manual_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    # No NUL: the database refuses it.
    notes: str | None = Field(default=None, max_length=1000, pattern=r"^[^\x00]*$")


class TransactionOut(BaseModel):
    id: int
    item_id: int
    delta: int
    source: str
    undone: bool
    created_at: datetime
    game_id: str
    name: str
    translation: str | None = None
    set_code: str
    finish: str
    condition: str
    language: str


class GameValueOut(BaseModel):
    game_id: str
    currency: str
    total: Decimal
    quantity: int
    priced: int
    unpriced: int


class CurrencyTotalOut(BaseModel):
    currency: str
    total: Decimal


class ValueOut(BaseModel):
    # Total in the user's price source currency; games priced in another one are only in
    # `totals` (per currency, never added up).
    currency: str
    total: Decimal
    totals: list[CurrencyTotalOut]
    quantity: int
    games: list[GameValueOut]


class ValuePointOut(BaseModel):
    date: date
    value: Decimal


class ValueHistoryOut(BaseModel):
    currency: str
    points: list[ValuePointOut]


class ImportErrorOut(BaseModel):
    line: int
    message: str


class ImportOut(BaseModel):
    rows: int
    imported: int
    dry_run: bool
    errors: list[ImportErrorOut]


def currency(game_id: str, wanted: str) -> str:
    chosen = collection.pricing(game_id, wanted)
    return chosen.currency if chosen else price_sources()[wanted].currency


def _item_query():
    return select(CollectionItem).options(
        selectinload(CollectionItem.printing).selectinload(Printing.card),
        selectinload(CollectionItem.printing).selectinload(Printing.set),
    )


def copy_image(printing: Printing, language: str, picked: str | None) -> str | None:
    """Picture of a copy: in its own language, else the game's fallback language (English,
    Japanese for Asian games), else `picked` (the card's usual picture) unless the game
    has no fallback (Pokémon China: placeholder)."""
    available = {
        lang for lang in images.image_languages(printing) if printing.image_paths.get(lang) != ""
    }
    fallback = image_fallback(registry().get(printing.set.game_id))
    lang = next((lang for lang in (language, fallback) if lang in available), None)
    if lang:
        return image_link(printing, lang)
    return picked if fallback else None


async def _items_out(
    session: SessionDep, items: list[CollectionItem], lang: str, wanted: str
) -> list[ItemOut]:
    games = {i.printing_id: i.printing.set.game_id for i in items}
    prices = await collection.user_prices(session, wanted, games)
    trends = await collection.price_trends(session, wanted, games, prices)
    card_names, printing_names = await load_names(session, (i.printing.card_id for i in items))
    out = []
    for item in items:
        printing = item.printing
        shown, image = show_printing(printing, card_names, printing_names, lang, printing.card.name)
        point = prices.get((item.printing_id, item.finish))
        unit = collection.unit_price(item, prices)
        out.append(
            ItemOut(
                id=item.id,
                printing_id=printing.id,
                card_id=printing.card_id,
                game_id=printing.set.game_id,
                name=shown.name,
                translation=shown.translation,
                colors=printing.card.colors,
                set=ItemSetOut(id=printing.set.id, code=printing.set.code, name=printing.set.name),
                collector_number=printing.collector_number,
                rarity=printing.rarity,
                rarity_code=rarity_code(printing),
                image=copy_image(printing, item.language, image),
                back_image=back_image_link(printing),
                orientation=orientation(printing),
                finish=item.finish,
                condition=item.condition,
                language=item.language,
                quantity=item.quantity,
                manual_price=item.manual_price,
                market_price=point.trend if point else None,
                currency=currency(item.printing.set.game_id, wanted),
                price_date=point.date if point else None,
                unit_price=unit,
                total=None if unit is None else unit * item.quantity,
                trends=TrendsOut(
                    **{
                        period: TrendOut(direction=t.direction, change=t.change)
                        for period, t in trends.get((item.printing_id, item.finish), {}).items()
                        if t is not None
                    }
                ),
                notes=item.notes,
                updated_at=item.updated_at,
            )
        )
    return out


async def _item_out(session: SessionDep, item_id: int, lang: str, wanted: str) -> ItemOut:
    session.expire_all()
    item = await session.scalar(_item_query().where(CollectionItem.id == item_id))
    return (await _items_out(session, [item], lang, wanted))[0]


async def _own_item(session: SessionDep, user_id: int, item_id: int) -> CollectionItem:
    item = await session.scalar(
        select(CollectionItem).where(
            CollectionItem.id == item_id, CollectionItem.user_id == user_id
        )
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    return item


def _conflict(exc: StockError) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.get("")
async def list_items(
    user: CurrentUser,
    session: SessionDep,
    game: str | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    set_id: int | None = None,
    color: Annotated[list[str] | None, Query()] = None,
    color_mode: Literal["include", "exact"] = "include",
    finish: str | None = None,
    condition: Condition | None = None,
    language: str | None = None,
    include_empty: bool = False,
    sort: Literal["name", "set", "updated", "quantity", "price_asc", "price_desc"] = "name",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 50,
) -> ItemPageOut:
    """The current user's items with resolved prices."""
    query = (
        _item_query()
        .join(Printing, CollectionItem.printing_id == Printing.id)
        .join(Card, Printing.card_id == Card.id)
        .join(CardSet, Printing.set_id == CardSet.id)
        .where(CollectionItem.user_id == user.id)
    )
    if not include_empty:
        query = query.where(CollectionItem.quantity > 0)
    if game:
        query = query.where(CardSet.game_id == game)
    if q:
        query = query.where(exists().where(CardName.card_id == Card.id, name_matches(q)))
    if set_id is not None:
        query = query.where(Printing.set_id == set_id)
    if color:
        query = query.where(Card.colors.contains(color))
        if color_mode == "exact":
            query = query.where(Card.colors.contained_by(color))
    if finish:
        query = query.where(CollectionItem.finish == finish)
    if condition:
        query = query.where(CollectionItem.condition == condition)
    if language:
        query = query.where(CollectionItem.language == language)

    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    name = display_name(user.language)
    # Unit price as shown: manual price, else latest market price of that finish.
    sources = {
        game_id: chosen.source
        for game_id in registry()
        if (chosen := collection.pricing(game_id, user.price_source)) is not None
    }
    market = (
        select(PriceSnapshot.trend)
        .where(
            PriceSnapshot.printing_id == CollectionItem.printing_id,
            PriceSnapshot.finish == CollectionItem.finish,
            PriceSnapshot.source == case(sources, value=CardSet.game_id, else_=""),
            PriceSnapshot.trend.is_not(None),
        )
        .order_by(PriceSnapshot.date.desc())
        .limit(1)
        .correlate(CollectionItem)
        .scalar_subquery()
    )
    price = func.coalesce(CollectionItem.manual_price, market)
    order = {
        "price_asc": (price.asc().nulls_last(), name),
        "price_desc": (price.desc().nulls_last(), name),
        "name": (name, CardSet.code, number_sort_key(Printing.collector_number)),
        "set": (
            CardSet.release_date.desc().nulls_last(),
            CardSet.code,
            number_sort_key(Printing.collector_number),
        ),
        "updated": (CollectionItem.updated_at.desc(),),
        "quantity": (CollectionItem.quantity.desc(), name),
    }[sort]
    items = (
        await session.scalars(
            query.order_by(*order, CollectionItem.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return ItemPageOut(
        items=await _items_out(session, list(items), user.language, user.price_source),
        total=total or 0,
        page=page,
        page_size=page_size,
    )


@router.post("/adjust")
async def adjust(body: AdjustIn, user: CurrentUser, session: SessionDep) -> AdjustOut:
    """Add (positive delta) or remove (negative delta) copies of a printing variant."""
    printing = await session.get(Printing, body.printing_id)
    if printing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Printing not found")
    variant = Variant(body.finish, body.condition, body.language)
    try:
        item, transaction = await collection.adjust(
            session, user.id, printing, variant, body.delta, body.source
        )
    except StockError as exc:
        await session.rollback()
        raise _conflict(exc) from exc
    item_id, transaction_id = item.id, transaction.id
    await session.commit()
    return AdjustOut(
        item=await _item_out(session, item_id, user.language, user.price_source),
        transaction_id=transaction_id,
    )


@router.get("/items/{item_id}")
async def get_item(item_id: int, user: CurrentUser, session: SessionDep) -> ItemOut:
    await _own_item(session, user.id, item_id)
    return await _item_out(session, item_id, user.language, user.price_source)


@router.patch("/items/{item_id}")
async def update_item(
    item_id: int, body: ItemUpdateIn, user: CurrentUser, session: SessionDep
) -> ItemOut:
    """Set quantity (recorded as a stock change), manual price or notes.
    Send `manual_price: null` to go back to API prices."""
    item = await _own_item(session, user.id, item_id)
    fields = body.model_fields_set
    if "manual_price" in fields:
        item.manual_price = body.manual_price
    if "notes" in fields:
        item.notes = body.notes or None
    if body.quantity is not None:
        try:
            await collection.set_quantity(session, item, body.quantity, "web")
        except StockError as exc:
            await session.rollback()
            raise _conflict(exc) from exc
    await session.commit()
    return await _item_out(session, item_id, user.language, user.price_source)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: int, user: CurrentUser, session: SessionDep) -> None:
    """Forget an item and its stock history."""
    item = await _own_item(session, user.id, item_id)
    await session.delete(item)
    await session.commit()


@router.get("/transactions")
async def list_transactions(
    user: CurrentUser,
    session: SessionDep,
    item_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[TransactionOut]:
    query = (
        select(StockTransaction, CollectionItem, Printing, Card.name)
        .join(CollectionItem, StockTransaction.item_id == CollectionItem.id)
        .join(Printing, CollectionItem.printing_id == Printing.id)
        .join(Card, Printing.card_id == Card.id)
        .join(CardSet, Printing.set_id == CardSet.id)
        .options(contains_eager(Printing.set))
        .where(StockTransaction.user_id == user.id)
        .order_by(StockTransaction.id.desc())
        .limit(limit)
    )
    if item_id is not None:
        query = query.where(StockTransaction.item_id == item_id)
    rows = (await session.execute(query)).all()
    card_names, printing_names = await load_names(session, (p.card_id for _, _, p, _ in rows))
    out = []
    for t, item, printing, canonical in rows:
        shown, _ = show_printing(printing, card_names, printing_names, user.language, canonical)
        out.append(
            TransactionOut(
                id=t.id,
                item_id=t.item_id,
                delta=t.delta,
                source=t.source,
                undone=t.undone,
                created_at=t.created_at,
                game_id=printing.set.game_id,
                name=shown.name,
                translation=shown.translation,
                set_code=printing.set.code,
                finish=item.finish,
                condition=item.condition,
                language=item.language,
            )
        )
    return out


@router.post("/transactions/{transaction_id}/undo")
async def undo_transaction(transaction_id: int, user: CurrentUser, session: SessionDep) -> ItemOut:
    try:
        item = await collection.undo(session, user.id, transaction_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except StockError as exc:
        await session.rollback()
        raise _conflict(exc) from exc
    item_id = item.id
    await session.commit()
    return await _item_out(session, item_id, user.language, user.price_source)


@router.get("/value")
async def value(user: CurrentUser, session: SessionDep) -> ValueOut:
    """Current collection value, per game and overall."""
    games = await collection.value_by_game(session, user.id, user.price_source)
    totals: dict[str, Decimal] = {}
    for game in games:
        totals[game.currency] = totals.get(game.currency, Decimal(0)) + game.total
    main = price_sources()[user.price_source].currency
    return ValueOut(
        currency=main,
        total=totals.get(main, Decimal(0)),
        totals=[CurrencyTotalOut(currency=c, total=t) for c, t in totals.items()],
        quantity=sum(g.quantity for g in games),
        games=[GameValueOut.model_validate(g, from_attributes=True) for g in games],
    )


class MoverOut(BaseModel):
    item: ItemOut
    # Value change of the copies held over the period (market price), in `item.currency`.
    change: Decimal


class MoversOut(BaseModel):
    period: Literal["d1", "d7", "d30"]
    risers: list[MoverOut]
    fallers: list[MoverOut]


@router.get("/movers")
async def movers(
    user: CurrentUser,
    session: SessionDep,
    period: Literal["d1", "d7", "d30"] = "d7",
    limit: Annotated[int, Query(ge=1, le=50)] = 5,
) -> MoversOut:
    """Owned items whose market price moved most over the period, by value of the copies
    held (price change × quantity): biggest rises and falls."""
    items = (
        await session.scalars(
            _item_query()
            .join(Printing, CollectionItem.printing_id == Printing.id)
            .where(CollectionItem.user_id == user.id, CollectionItem.quantity > 0)
        )
    ).all()
    games = {i.printing_id: i.printing.set.game_id for i in items}
    now = await collection.user_prices(session, user.price_source, games)
    trends = await collection.price_trends(session, user.price_source, games, now)
    changes: list[tuple[Decimal, CollectionItem]] = []
    for item in items:
        key = (item.printing_id, item.finish)
        trend, point = trends.get(key, {}).get(period), now.get(key)
        if trend is None or point is None or trend.direction == "flat":
            continue
        past = point.trend / (1 + Decimal(str(trend.change)))
        changes.append(((point.trend - past) * item.quantity, item))
    rising = sorted((c for c in changes if c[0] > 0), key=lambda c: -c[0])[:limit]
    falling = sorted((c for c in changes if c[0] < 0), key=lambda c: c[0])[:limit]
    described = {
        out.id: out
        for out in await _items_out(
            session, [i for _, i in rising + falling], user.language, user.price_source
        )
    }
    return MoversOut(
        period=period,
        risers=[MoverOut(item=described[i.id], change=round(c, 2)) for c, i in rising],
        fallers=[MoverOut(item=described[i.id], change=round(c, 2)) for c, i in falling],
    )


class ShareOut(BaseModel):
    key: str
    label: str
    value: Decimal
    quantity: int


class ChangeOut(BaseModel):
    days: int
    # Value then (None: no price history that far back) and now.
    past: Decimal | None
    now: Decimal


class TopItemOut(BaseModel):
    item: ItemOut
    unit: Decimal
    value: Decimal


class FinanceOut(BaseModel):
    currency: str
    value: Decimal
    quantity: int
    printings: int
    priced: int
    unpriced: int
    average: Decimal | None
    median: Decimal | None
    other_currencies: list[str]
    changes: list[ChangeOut]
    history: list[ValuePointOut]
    by_game: list[ShareOut]
    by_set: list[ShareOut]
    by_rarity: list[ShareOut]
    by_condition: list[ShareOut]
    by_language: list[ShareOut]
    by_finish: list[ShareOut]
    by_band: list[ShareOut]
    top: list[TopItemOut]
    # Share of the 10 dearest items in the value (0.4 = 40 %).
    top_share: float | None


@router.get("/finance")
async def finance(user: CurrentUser, session: SessionDep, game: str | None = None) -> FinanceOut:
    """Market value figures of the collection, or of one game's cards: totals, change
    over 1 to 365 days, value over the last year and how it splits (game, set, rarity,
    condition, language, finish, price band). Without a game, games priced in another
    currency than the user's price source are left out (listed in `other_currencies`)."""
    items = (
        await session.scalars(
            _item_query()
            .join(Printing, CollectionItem.printing_id == Printing.id)
            .where(CollectionItem.user_id == user.id, CollectionItem.quantity > 0)
        )
    ).all()
    report = await collection.finance(session, user.id, list(items), user.price_source, game)
    described = {
        out.id: out
        for out in await _items_out(
            session, [item for item, _, _ in report.top], user.language, user.price_source
        )
    }

    def shares(found: list[collection.Share]) -> list[ShareOut]:
        return [ShareOut.model_validate(s, from_attributes=True) for s in found]

    return FinanceOut(
        currency=report.currency,
        value=report.value,
        quantity=report.quantity,
        printings=report.printings,
        priced=report.priced,
        unpriced=report.unpriced,
        average=report.average,
        median=report.median,
        other_currencies=report.other_currencies,
        changes=[
            ChangeOut(days=days, past=change[0] if change else None, now=report.value)
            for days, change in report.changes.items()
        ],
        history=[ValuePointOut(date=d, value=v) for d, v in report.history],
        by_game=shares(report.by_game),
        by_set=shares(report.by_set),
        by_rarity=shares(report.by_rarity),
        by_condition=shares(report.by_condition),
        by_language=shares(report.by_language),
        by_finish=shares(report.by_finish),
        by_band=shares(report.by_band),
        top=[
            TopItemOut(item=described[item.id], unit=unit, value=value)
            for item, unit, value in report.top
        ],
        top_share=report.top_share,
    )


@router.get("/value/history")
async def value_history(
    user: CurrentUser,
    session: SessionDep,
    game: str | None = None,
    days: Annotated[int, Query(ge=1, le=3650)] = 90,
) -> ValueHistoryOut:
    """Daily value of current holdings over the last `days` days. Without a game, games
    priced in another currency than the user's price source are left out."""
    end = date.today()
    currency, history = await collection.value_history(
        session, user.id, user.price_source, game, end - timedelta(days=days - 1), end
    )
    return ValueHistoryOut(
        currency=currency, points=[ValuePointOut(date=d, value=v) for d, v in history]
    )


@router.get("/export.csv")
async def export_csv(user: CurrentUser, session: SessionDep, game: str | None = None) -> Response:
    content = await csv_io.export_csv(session, user.id, game)
    filename = f"collection-{game or 'all'}-{date.today().isoformat()}.csv"
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import")
async def import_csv(
    user: CurrentUser,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    mode: Literal["add", "set"] = "add",
    dry_run: bool = False,
) -> ImportOut:
    """Import a CSV (see export format). Nothing is imported if any row is invalid.
    `add` adds quantities; `set` makes stored quantities equal to the file's."""
    data = await file.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File larger than 5 MB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File must be UTF-8 text") from exc
    report = await csv_io.import_csv(session, user.id, text, mode == "set", dry_run)
    return ImportOut(
        rows=report.rows,
        imported=report.imported,
        dry_run=dry_run,
        errors=[ImportErrorOut(line=e.line, message=e.message) for e in report.errors[:200]],
    )
