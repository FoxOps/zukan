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

from sqlalchemy import Float, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.games.base import GameProvider, OcrHints, OcrLine, registry
from app.games.ocr import chinese_variants, has_cjk
from app.models import Card, CardName, CardSet, Printing

MAX_CARDS = 8
MAX_PRINTINGS = 30
# Below this similarity a name match is noise.
MIN_SIMILARITY = 0.3
GOOD_SIMILARITY = 0.6
# With the collector number read, from this similarity the name is taken as confirmed.
NUMBER_NAME_SIMILARITY = 0.5


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


def number_matches(column, number: str):
    """Compare collector numbers ignoring zero padding ("007" == "7")."""
    return func.ltrim(column, "0") == (number.lstrip("0") or "0")


async def _exact(session: AsyncSession, game_id: str, hints: OcrHints) -> list[Printing]:
    if not (hints.set_code and hints.collector_number):
        return []
    lookup = getattr(registry().get(game_id), "code_lookup", None)
    found = lookup(hints.collector_number) if lookup else None
    if found:
        # A code printed differently than stored ("BETB-KR024" under "BETB-EN024").
        set_codes, numbers = found
        printings = list(
            await session.scalars(
                select(Printing)
                .join(CardSet)
                .where(
                    CardSet.game_id == game_id,
                    func.lower(CardSet.code).in_([c.lower() for c in set_codes]),
                    Printing.collector_number.in_(numbers),
                )
            )
        )
        if printings:
            return printings
    code = hints.set_code.lower()
    return list(
        await session.scalars(
            select(Printing)
            .join(CardSet)
            .where(
                CardSet.game_id == game_id,
                or_(func.lower(CardSet.code) == code, func.lower(CardSet.external_id) == code),
                number_matches(Printing.collector_number, hints.collector_number),
            )
        )
    )


async def _by_number(
    session: AsyncSession, game_id: str, number: str, lang: str | None
) -> list[Printing]:
    """Printings with that number; common numbers ("001") exist in hundreds of sets, so
    the detected language and newer sets come first when there are too many."""
    query = (
        select(Printing)
        .join(CardSet)
        .where(CardSet.game_id == game_id, number_matches(Printing.collector_number, number))
    )
    if lang:
        query = query.order_by(Printing.languages.contains([lang]).desc())
    return list(
        await session.scalars(
            query.order_by(CardSet.release_date.desc().nulls_last(), Printing.id).limit(2000)
        )
    )


async def _name_similarity(
    session: AsyncSession, game_id: str, names: list[str], card_ids: set[int] | None = None
) -> dict[int, float]:
    """Best similarity per card between any of `names` and the card's names (each face of
    double-faced names counts on its own). Case and accents are ignored."""
    if not names:
        return {}
    texts = [func.lower(func.f_unaccent(name)) for name in names]
    scores = [
        func.greatest(
            func.similarity(CardName.search_name, text),
            func.similarity(func.split_part(CardName.search_name, " // ", 1), text),
        )
        for text in texts
    ]
    # Asian names are short and unspaced: a misread or extra glyph costs most of their
    # few trigrams. A name found inside the read text (or the reverse) scores by length.
    contained = []
    for name, text in zip(names, texts, strict=True):
        if not has_cjk(name):
            continue
        name_length = func.char_length(CardName.search_name)
        text_length = func.char_length(text)
        inside = and_(name_length >= 2, func.strpos(text, CardName.search_name) > 0)
        around = func.strpos(CardName.search_name, text) > 0
        scores.append(
            case(
                (inside, cast(name_length, Float) / func.greatest(text_length, 1)),
                (around, cast(text_length, Float) / func.greatest(name_length, 1)),
                else_=0.0,
            )
        )
        contained.append(or_(inside, around))
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
        query = query.where(
            or_(*(CardName.search_name.op("%")(text) for text in texts), *contained)
        )
    return {card_id: float(score) for card_id, score in await session.execute(query)}


async def _identify_game(
    session: AsyncSession, provider: GameProvider, lines: list[OcrLine]
) -> tuple[OcrHints, dict[int, Candidate]]:
    hints = provider.parse_ocr(lines)
    names = chinese_variants([n for n in [hints.name, *hints.other_names] if n])
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
        numbered = await _by_number(session, provider.id, hints.collector_number, hints.lang)
        cards = {p.card_id for p in numbered}
        similarity = await _name_similarity(session, provider.id, names, cards) if cards else {}
        for printing in numbered:
            score = similarity.get(printing.card_id, 0)
            if score >= NUMBER_NAME_SIMILARITY:
                # The number read and a fair name: above any name-only match ("M Camerupt
                # ex" + 022 is Mega Camerupt ex 022, not the old M Camerupt-EX).
                add(printing.card_id, 0.9 + 0.09 * score, "number_name", [printing.id])
            elif score >= MIN_SIMILARITY:
                add(printing.card_id, 0.6 + 0.4 * score, "number_name", [printing.id])

    if hints.name:
        # Other lines only matter when the expected name line reads badly.
        by_name = await _name_similarity(session, provider.id, chinese_variants([hints.name]))
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


def other_game(lines: list[OcrLine], game_id: str) -> str | None:
    """Another supported game whose card the text clearly is (its markers: copyright
    line, set code format...), when the chosen game's markers are not there."""
    if registry()[game_id].parse_ocr(lines).recognized:
        return None
    for provider in registry().values():
        if provider.id != game_id and provider.parse_ocr(lines).recognized:
            return provider.id
    return None


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
        # What was read, from the game the text looks most like (shown to the user).
        best = max(
            hints_by_game.values(),
            key=lambda h: (h.recognized, bool(h.set_code and h.collector_number), bool(h.name)),
            default=OcrHints(),
        )
        return Identification(only, best, [])

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
