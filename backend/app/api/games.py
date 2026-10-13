from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.games.base import registry
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


class GameOut(BaseModel):
    id: str
    name: str
    colors: list[ColorOut]
    finishes: list[FinishOut]
    languages: list[str]
    has_prices: bool


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
            has_prices=p.price_source is not None,
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
    return FileResponse(path, headers={"Cache-Control": "private, max-age=2592000"})
