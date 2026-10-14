"""Card names in the reader's language.

A card is named in the interface language when a name exists in it, else in English,
else in Japanese, else by its canonical name (the language it was first catalogued in),
the same order as card images (`images.FALLBACK_LANGUAGES`). Names valid for every
printing win over names of a single printing.
"""

from collections.abc import Iterable

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Card, CardName
from app.services.images import FALLBACK_LANGUAGES


def display_name(lang: str) -> ColumnElement[str]:
    """SQL expression naming `Card` in `lang` (for selecting and sorting)."""
    languages = list(dict.fromkeys([lang, *FALLBACK_LANGUAGES]))
    best = (
        select(CardName.name)
        .where(CardName.card_id == Card.id, CardName.lang.in_(languages))
        .order_by(
            case(*((CardName.lang == code, rank) for rank, code in enumerate(languages))),
            CardName.printing_id.is_not(None),
            CardName.id,
        )
        .limit(1)
        .correlate(Card)
        .scalar_subquery()
    )
    return func.coalesce(best, Card.name)


async def display_names(
    session: AsyncSession, card_ids: Iterable[int], lang: str
) -> dict[int, str]:
    ids = set(card_ids)
    if not ids:
        return {}
    rows = await session.execute(select(Card.id, display_name(lang)).where(Card.id.in_(ids)))
    return {card_id: name for card_id, name in rows}
