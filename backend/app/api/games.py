import time

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import case, func, select

from app.api.deps import CurrentUser, SessionDep
from app.games.base import registry
from app.models import Card, Printing
from app.prices.base import game_sources
from app.services.symbols import symbol_file

router = APIRouter(prefix="/games", tags=["games"])


class ColorOut(BaseModel):
    code: str
    name: str
    hex: str
    # Official symbol, once downloaded.
    icon: str | None


class FinishOut(BaseModel):
    code: str
    name: str


class PriceSourceOut(BaseModel):
    id: str
    name: str
    currency: str


class FilterOut(BaseModel):
    # Search parameter: `attr=<key>:<value>` on /api/cards.
    key: str
    label: str


class GameOut(BaseModel):
    id: str
    name: str
    colors: list[ColorOut]
    finishes: list[FinishOut]
    languages: list[str]
    # Advanced catalog search filters; values from /api/games/{id}/filters.
    filters: list[FilterOut]
    # Markets with prices for this game, the main one first.
    price_sources: list[PriceSourceOut]
    has_prices: bool
    # Deprecated (app 0.3): Cardmarket URL segment, see PrintingOut.links.
    cardmarket: str | None
    # Notice the publisher requires fan tools to show (trademarks, no endorsement).
    legal_notice: str | None = None


@router.get("")
async def list_games(_: CurrentUser) -> list[GameOut]:
    return [
        GameOut(
            id=p.id,
            name=p.name,
            colors=[
                ColorOut(
                    code=c.code,
                    name=c.name,
                    hex=c.hex,
                    icon=f"/api/games/{p.id}/colors/{c.code}/icon"
                    if symbol_file(p.id, c.code)
                    else None,
                )
                for c in p.colors
            ],
            finishes=[FinishOut(code=f.code, name=f.name) for f in p.finishes],
            languages=p.languages,
            filters=[FilterOut(key=f.key, label=f.label) for f in getattr(p, "filters", [])],
            price_sources=[
                PriceSourceOut(id=s.id, name=s.name, currency=s.currency)
                for s in game_sources(p.id)
            ],
            has_prices=bool(game_sources(p.id)),
            cardmarket=getattr(p, "cardmarket_path", None),
            legal_notice=getattr(p, "legal_notice", None),
        )
        for p in registry().values()
    ]


@router.get("/{game_id}/colors/{code}/icon")
async def color_icon(game_id: str, code: str, _: CurrentUser) -> FileResponse:
    provider = registry().get(game_id)
    if provider is None or code not in {c.code for c in provider.colors}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown color")
    path = symbol_file(game_id, code)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Symbol not downloaded yet")
    # SVG files: never run anything they contain.
    return FileResponse(
        path,
        headers={
            "Cache-Control": "private, max-age=2592000",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
        },
    )


# Filter values change with catalog syncs only (weekly): computed at most once an hour.
_VALUES_TTL = 3600
_values: dict[str, tuple[float, dict[str, list[str]]]] = {}


def clear_filter_values(game_id: str) -> None:
    _values.pop(game_id, None)


async def filter_values(session: SessionDep, game_id: str) -> dict[str, list[str]]:
    cached = _values.get(game_id)
    if cached and time.monotonic() - cached[0] < _VALUES_TTL:
        return cached[1]
    values: dict[str, list[str]] = {}
    for f in getattr(registry()[game_id], "filters", []):
        if f.attribute is None:
            query = (
                select(Printing.rarity)
                .join(Card, Printing.card_id == Card.id)
                .where(Card.game_id == game_id, Printing.rarity.is_not(None))
            )
        else:
            data = Card.attributes[f.attribute]
            element = func.jsonb_array_elements_text(
                case((func.jsonb_typeof(data) == "array", data), else_=func.jsonb_build_array(data))
            )
            query = (
                select(element)
                .select_from(Card)
                .where(Card.game_id == game_id, Card.attributes.has_key(f.attribute))
            )
        found = {v for v in await session.scalars(query.distinct()) if v and v.strip()}
        values[f.key] = sorted(found, key=str.casefold)
    _values[game_id] = (time.monotonic(), values)
    return values


@router.get("/{game_id}/filters")
async def list_filter_values(
    game_id: str, _: CurrentUser, session: SessionDep
) -> dict[str, list[str]]:
    """Values of each advanced search filter of the game, by filter key."""
    if game_id not in registry():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown game")
    return await filter_values(session, game_id)
