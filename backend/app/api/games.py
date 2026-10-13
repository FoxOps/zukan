from dataclasses import asdict

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser
from app.games.base import registry

router = APIRouter(prefix="/games", tags=["games"])


class ColorOut(BaseModel):
    code: str
    name: str
    hex: str


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
            colors=[ColorOut(**asdict(c)) for c in p.colors],
            finishes=[FinishOut(**asdict(f)) for f in p.finishes],
            languages=p.languages,
            has_prices=p.price_source is not None,
        )
        for p in registry().values()
    ]
