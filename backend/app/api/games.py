import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import case, func, select

from app.api.deps import CurrentUser, SessionDep
from app.games.base import group_of, rarity_icon_file, rarity_of, registry
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


class RarityOut(BaseModel):
    # PrintingOut.rarity_code; rarities are listed lowest first.
    code: str
    name: str
    # Pictogram of the rarity, when the game has one.
    icon: str | None
    # Other pictograms for cards printed in some languages (Japanese, Chinese), by
    # language: clients show `icons[lang]` when there, else `icon`.
    icons: dict[str, str] = {}


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
    # Games of one family split by market (Pokémon TCG / Asia / China) share a group;
    # other games are a group of their own (group = id).
    group: str
    group_name: str
    # The game's market within its group ("International", "Asia", "TCG"...).
    region: str | None = None
    region_label: str | None = None
    colors: list[ColorOut]
    finishes: list[FinishOut]
    rarities: list[RarityOut] = []
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
            group=group_of(p.id),
            group_name=getattr(p, "group_name", None) or p.name,
            region=getattr(p, "region", None),
            region_label=getattr(p, "region_label", None),
            colors=[
                ColorOut(
                    code=c.code,
                    name=c.name,
                    hex=c.hex,
                    icon=_icon_link(
                        f"/api/games/{p.id}/colors/{c.code}/icon", symbol_file(p.id, c.code)
                    ),
                )
                for c in p.colors
            ],
            finishes=[FinishOut(code=f.code, name=f.name) for f in p.finishes],
            rarities=[
                RarityOut(
                    code=r.code,
                    name=r.name,
                    icon=_icon_link(
                        f"/api/games/{p.id}/rarities/{r.code}/icon", rarity_icon_file(p.id, r.code)
                    ),
                    icons=_language_icons(p, r.code),
                )
                for r in getattr(p, "rarities", [])
            ],
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
    return FileResponse(path, headers=_SYMBOL_HEADERS)


@router.get("/{game_id}/rarities/{code}/icon")
async def rarity_icon(
    game_id: str, code: str, _: CurrentUser, lang: Annotated[str | None, Query(max_length=8)] = None
) -> FileResponse:
    """The rarity's pictogram; `lang`: the one of cards printed in that language."""
    path = rarity_icon_file(game_id, code, lang) if game_id in registry() else None
    if path is None or code not in {r.code for r in getattr(registry()[game_id], "rarities", [])}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown rarity")
    return FileResponse(path, headers=_SYMBOL_HEADERS)


def _language_icons(provider: Any, code: str) -> dict[str, str]:
    """Links to the pictograms of the languages whose cards show another one."""
    plain = rarity_icon_file(provider.id, code)
    out = {}
    for lang in provider.languages:
        path = rarity_icon_file(provider.id, code, lang)
        if path is not None and path != plain:
            url = f"/api/games/{provider.id}/rarities/{code}/icon?lang={lang}"
            if link := _icon_link(url, path):
                out[lang] = link.replace("?v=", "&v=")
    return out


def _icon_link(url: str, path: Path | None) -> str | None:
    """Link to a pictogram, changing when its file is replaced (browsers keep them a month)."""
    if path is None:
        return None
    try:
        return f"{url}?v={int(path.stat().st_mtime)}"
    except OSError:
        return None


# SVG files: never run anything they contain.
_SYMBOL_HEADERS = {
    "Cache-Control": "private, max-age=2592000",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
}


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
        if f.attribute is None:
            # Rarities lowest first, unknown spellings after them.
            order = {r: i for i, r in enumerate(getattr(registry()[game_id], "rarities", []))}
            values[f.key] = sorted(
                found, key=lambda v: (order.get(rarity_of(game_id, v), len(order)), v.casefold())
            )
        else:
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
