"""Identify cards from OCR text sent by the scanner app.

Each game provider reads hints (name, set code, collector number, language) from the
recognized lines. Candidates come from, in order of confidence:
1. set code + collector number: the exact printing (language independent, which makes
   Japanese, Korean or Chinese cards easy to identify);
2. collector number + similar name;
3. trigram similarity of the name against card names in every language.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.games.base import GameProvider, OcrHints, OcrLine, registry
from app.models import Card, CardName, CardSet, Printing

MAX_CARDS = 8
MAX_PRINTINGS = 30
# Below this similarity a name match is noise.
MIN_SIMILARITY = 0.3
GOOD_SIMILARITY = 0.6


@dataclass
class Candidate:
    score: float
    match: str  # set_number | number_name | name
    # Best matching printings first; the rest of the card's printings follow.
    printing_ids: list[int] = field(default_factory=list)
    card: Card | None = None


@dataclass
class Identification:
    game_id: str | None
    hints: OcrHints
    candidates: list[Candidate]


def _number_matches(column, number: str):
    """Compare collector numbers ignoring zero padding ("007" == "7")."""
    return func.ltrim(column, "0") == (number.lstrip("0") or "0")


async def _exact(session: AsyncSession, game_id: str, hints: OcrHints) -> list[Printing]:
    if not (hints.set_code and hints.collector_number):
        return []
    code = hints.set_code.lower()
    return list(
        await session.scalars(
            select(Printing)
            .join(CardSet)
            .where(
                CardSet.game_id == game_id,
                or_(func.lower(CardSet.code) == code, func.lower(CardSet.external_id) == code),
                _number_matches(Printing.collector_number, hints.collector_number),
            )
        )
    )


async def _by_number(session: AsyncSession, game_id: str, number: str) -> list[Printing]:
    return list(
        await session.scalars(
            select(Printing)
            .join(CardSet)
            .where(CardSet.game_id == game_id, _number_matches(Printing.collector_number, number))
            .limit(2000)
        )
    )


async def _name_similarity(
    session: AsyncSession, game_id: str, names: list[str], card_ids: set[int] | None = None
) -> dict[int, float]:
    """Best similarity per card between any of `names` and the card's names (each face of
    double-faced names counts on its own)."""
    if not names:
        return {}
    scores = [
        func.greatest(
            func.similarity(CardName.name, name),
            func.similarity(func.split_part(CardName.name, " // ", 1), name),
        )
        for name in names
    ]
    best = func.max(func.greatest(*scores) if len(scores) > 1 else scores[0])
    query = (
        select(CardName.card_id, best)
        .join(Card, Card.id == CardName.card_id)
        .where(Card.game_id == game_id)
        .group_by(CardName.card_id)
        .order_by(best.desc())
        .limit(MAX_CARDS * 3)
    )
    if card_ids is not None:
        query = query.where(CardName.card_id.in_(card_ids))
    else:
        # Trigram index lookup (similarity above pg_trgm.similarity_threshold, 0.3).
        query = query.where(or_(*(CardName.name.op("%")(name) for name in names)))
    return {card_id: float(score) for card_id, score in await session.execute(query)}


async def _identify_game(
    session: AsyncSession, provider: GameProvider, lines: list[OcrLine]
) -> tuple[OcrHints, dict[int, Candidate]]:
    hints = provider.parse_ocr(lines)
    names = [n for n in [hints.name, *hints.other_names] if n]
    # Text that clearly belongs to this game (copyright line...) wins ties between games.
    bonus = 0.05 if hints.recognized else 0.0
    found: dict[int, Candidate] = {}

    def add(card_id: int, score: float, match: str, printing_ids: list[int]) -> None:
        current = found.get(card_id)
        if current is None or score + bonus > current.score:
            found[card_id] = Candidate(score + bonus, match, printing_ids)

    exact = await _exact(session, provider.id, hints)
    if exact:
        similarity = await _name_similarity(session, provider.id, names, {p.card_id for p in exact})
        for printing in exact:
            score = 1.0 + similarity.get(printing.card_id, 0) / 10
            add(printing.card_id, score, "set_number", [printing.id])
    elif hints.collector_number and names:
        numbered = await _by_number(session, provider.id, hints.collector_number)
        cards = {p.card_id for p in numbered}
        similarity = await _name_similarity(session, provider.id, names, cards) if cards else {}
        for printing in numbered:
            score = similarity.get(printing.card_id, 0)
            if score >= MIN_SIMILARITY:
                add(printing.card_id, 0.6 + 0.4 * score, "number_name", [printing.id])

    if hints.name:
        # Other lines only matter when the expected name line reads badly.
        by_name = await _name_similarity(session, provider.id, [hints.name])
        if max(by_name.values(), default=0) < GOOD_SIMILARITY and hints.other_names:
            by_name = await _name_similarity(session, provider.id, names)
        for card_id, score in by_name.items():
            if card_id not in found and score >= MIN_SIMILARITY:
                add(card_id, 0.9 * score, "name", [])
    return hints, found


def _printing_order(printing: Printing, lang: str | None) -> tuple:
    """Printings in the detected language first, then the newest."""
    return (
        0 if lang and lang in printing.languages else 1,
        -(printing.set.release_date or date.min).toordinal(),
    )


async def identify(
    session: AsyncSession, lines: list[OcrLine], game_id: str | None = None
) -> Identification:
    providers = [registry()[game_id]] if game_id else list(registry().values())
    # Games whose markers appear in the text are searched first; a printing-level match
    # there makes searching the other games pointless (and each costs a name lookup).
    providers.sort(key=lambda p: not p.parse_ocr(lines).recognized)
    found: dict[int, Candidate] = {}
    hints_by_game: dict[str, OcrHints] = {}
    for provider in providers:
        hints, candidates = await _identify_game(session, provider, lines)
        hints_by_game[provider.id] = hints
        found.update(candidates)
        if hints.recognized and any(c.score >= 1.0 for c in candidates.values()):
            break

    ranked = sorted(found.items(), key=lambda kv: kv[1].score, reverse=True)[:MAX_CARDS]
    if not ranked:
        only = providers[0].id if len(providers) == 1 else None
        return Identification(only, hints_by_game.get(only, OcrHints()) if only else OcrHints(), [])

    cards = {
        c.id: c
        for c in await session.scalars(
            select(Card)
            .where(Card.id.in_([card_id for card_id, _ in ranked]))
            .options(selectinload(Card.printings).selectinload(Printing.set))
        )
    }
    best_game = cards[ranked[0][0]].game_id
    hints = hints_by_game[best_game]
    result = []
    for card_id, candidate in ranked:
        card = cards[card_id]
        matched = set(candidate.printing_ids)
        rest = sorted(
            (p for p in card.printings if p.id not in matched),
            key=lambda p: _printing_order(p, hints_by_game[card.game_id].lang),
        )
        candidate.card = card
        candidate.printing_ids = (candidate.printing_ids + [p.id for p in rest])[:MAX_PRINTINGS]
        result.append(candidate)
    return Identification(best_game, hints, result)
