from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, StringConstraints

from app.api.catalog import PrintingOut, describe_printings
from app.api.deps import CurrentUser, SessionDep
from app.core.http import http_client
from app.games.base import OcrLine, registry
from app.models import Printing
from app.services import identify, lookup
from app.services.names import display_names

router = APIRouter(prefix="/scan", tags=["scan"])

Fraction = Annotated[float, Field(ge=0, le=1)]


class OcrLineIn(BaseModel):
    text: Annotated[str, StringConstraints(max_length=300)]
    # Optional box as fractions of the card/frame size (0 = left/top).
    left: Fraction | None = None
    top: Fraction | None = None
    width: Fraction | None = None
    height: Fraction | None = None


class IdentifyIn(BaseModel):
    # Restrict to one game; all games when omitted.
    game: str | None = None
    lines: list[OcrLineIn] = Field(max_length=200)


class HintsOut(BaseModel):
    name: str | None
    set_code: str | None
    collector_number: str | None
    lang: str | None


class CandidateCardOut(BaseModel):
    id: int
    game_id: str
    name: str
    colors: list[str]


class CandidateOut(BaseModel):
    score: float
    # set_number: exact printing; number_name: number and similar name; name: name only.
    match: str
    card: CandidateCardOut
    # Most likely printing first; at most 30, see `printing_count` and
    # /api/cards/{id}/printings for the others.
    printings: list[PrintingOut]
    printing_count: int


class IdentifyOut(BaseModel):
    game_id: str | None
    detected: HintsOut
    candidates: list[CandidateOut]
    # The card was missing from the catalog and was just fetched from its game's source.
    fetched: bool = False


@router.post("/identify")
async def identify_card(body: IdentifyIn, user: CurrentUser, session: SessionDep) -> IdentifyOut:
    """Match OCR text from a card photo to catalog printings."""
    if body.game and body.game not in registry():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown game {body.game!r}")
    lines = [OcrLine(**line.model_dump()) for line in body.lines if line.text.strip()]
    result = await identify.identify(session, lines, body.game)
    fetched = False
    if not result.candidates and lines:
        # Not in the catalog (yet): ask the game's source, then match again.
        providers = [registry()[body.game]] if body.game else list(registry().values())
        async with http_client(timeout=20) as http:
            fetched = await lookup.look_up(session, http, providers, lines, bool(body.game))
        if fetched:
            result = await identify.identify(session, lines, body.game)
    names = await display_names(
        session, (c.card.id for c in result.candidates if c.card), user.language
    )
    candidates = []
    for candidate in result.candidates:
        card = candidate.card
        assert card is not None
        by_id: dict[int, Printing] = {p.id: p for p in card.printings}
        printings = [by_id[pid] for pid in candidate.printing_ids]
        candidates.append(
            CandidateOut(
                score=round(candidate.score, 3),
                match=candidate.match,
                card=CandidateCardOut(
                    id=card.id, game_id=card.game_id, name=names[card.id], colors=card.colors
                ),
                printings=await describe_printings(session, user, printings),
                printing_count=len(card.printings),
            )
        )
    hints = result.hints
    return IdentifyOut(
        game_id=result.game_id,
        detected=HintsOut(
            name=hints.name,
            set_code=hints.set_code,
            collector_number=hints.collector_number,
            lang=hints.lang,
        ),
        candidates=candidates,
        fetched=fetched,
    )
