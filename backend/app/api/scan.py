import logging
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, StringConstraints

from app.api.catalog import PrintingOut, describe_printings, load_names, show_card
from app.api.deps import CurrentUser, SessionDep
from app.core.config import get_settings
from app.core.http import http_client
from app.games.base import OcrLine, registry
from app.models import Printing
from app.services import identify, lookup

log = logging.getLogger(__name__)

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
    # Latin name next to the name of cards printed only in non-Latin scripts.
    translation: str | None = None
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
    # found: candidates. not_found: the text looks like a card (game markers, set code
    # and number) but none matches. other_game: a card of another supported game than the
    # one asked for (`detected_game`). not_a_card: nothing card-like was read.
    status: Literal["found", "not_found", "other_game", "not_a_card"] = "found"
    detected_game: str | None = None


# A card photo reads as several lines (name, type, rules, credits); a stray sign or
# label is one or two.
CARD_LINES = 4


@router.post("/identify")
async def identify_card(body: IdentifyIn, user: CurrentUser, session: SessionDep) -> IdentifyOut:
    """Match OCR text from a card photo to catalog printings."""
    if body.game and body.game not in registry():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown game {body.game!r}")
    lines = [OcrLine(**line.model_dump()) for line in body.lines if line.text.strip()]
    result = await identify.identify(session, lines, body.game)
    fetched = False
    other_game = None
    if not result.candidates and lines and body.game:
        other_game = identify.other_game(lines, body.game)
    if not result.candidates and lines and other_game is None:
        # Not in the catalog (yet): ask the game's source, then match again.
        providers = [registry()[body.game]] if body.game else list(registry().values())
        async with http_client(timeout=20) as http:
            fetched = await lookup.look_up(session, http, providers, lines, bool(body.game))
        if fetched:
            result = await identify.identify(session, lines, body.game)
    card_names, printing_names = await load_names(
        session, (c.card.id for c in result.candidates if c.card)
    )
    candidates = []
    for candidate in result.candidates:
        card = candidate.card
        assert card is not None
        by_id: dict[int, Printing] = {p.id: p for p in card.printings}
        printings = [by_id[pid] for pid in candidate.printing_ids]
        # Named as printed in the best matching printing's set.
        shown = show_card(
            card,
            card_names,
            printing_names,
            user.language,
            {printings[0].set_id} if printings else None,
        )
        candidates.append(
            CandidateOut(
                score=round(candidate.score, 3),
                match=candidate.match,
                card=CandidateCardOut(
                    id=card.id,
                    game_id=card.game_id,
                    name=shown.name.name,
                    translation=shown.name.translation,
                    colors=card.colors,
                ),
                printings=await describe_printings(session, user, printings),
                printing_count=len(card.printings),
            )
        )
    hints = result.hints
    if get_settings().scan_debug_log:
        read = [(line.text, line.left, line.top) for line in lines]
        # Warning level: shown with the server's default logging, only when asked for.
        log.warning(
            "scan game=%s lines=%r -> game=%s code=%s number=%s lang=%s name=%r found=%s",
            body.game,
            read,
            result.game_id,
            hints.set_code,
            hints.collector_number,
            hints.lang,
            hints.name,
            [
                (c.card.name, [p.id for p in c.card.printings if p.id in c.printing_ids[:1]])
                for c in result.candidates[:3]
                if c.card
            ],
        )
    found_status: Literal["found", "not_found", "other_game", "not_a_card"]
    if candidates:
        found_status = "found"
    elif other_game is not None:
        found_status = "other_game"
    elif hints.recognized or hints.set_code or hints.collector_number:
        found_status = "not_found"
    elif body.game and hints.name and len(lines) >= CARD_LINES:
        # Games without set codes on the card (Sorcery): a name and enough text.
        found_status = "not_found"
    else:
        found_status = "not_a_card"
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
        status=found_status,
        detected_game=other_game,
    )
