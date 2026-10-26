"""Card names in the reader's language.

A card is named in the interface language when a name exists in it, else in English,
else in Japanese, else by its canonical name (the language it was first catalogued in),
the same order as card images (`images.FALLBACK_LANGUAGES`). Names valid for every
printing win over names of a single printing.

Whole catalogs are too large to sort by those names: they sort by `Card.sort_name`, the
card's name in the Latin alphabet (English first), kept up to date wherever names are
written (`update_sort_names`). Cards known only by non-Latin names have none and come last.
"""

from collections.abc import Iterable

from sqlalchemy import ColumnElement, Update, case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Card, CardName
from app.services.images import FALLBACK_LANGUAGES
from app.services.scripts import LANG_ORDER, NON_LATIN


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


def sort_name_query(game_id: str | None = None, card_ids: Iterable[int] | None = None) -> Update:
    """UPDATE setting `Card.sort_name` of a game's cards, of some cards, or of all: its
    Latin name in the "first available language" order (`scripts.LANG_ORDER`), names of
    every printing before names of one printing; None without any Latin name."""
    lang = func.lower(CardName.lang)
    base_lang = func.split_part(lang, "-", 1)
    best = (
        select(CardName.name)
        .where(CardName.card_id == Card.id, base_lang.not_in(sorted(NON_LATIN)))
        .order_by(
            case(
                *((lang == code, rank) for rank, code in enumerate(LANG_ORDER)),
                else_=len(LANG_ORDER),
            ),
            CardName.printing_id.is_not(None),
            CardName.lang,
            CardName.id,
        )
        .limit(1)
        .correlate(Card)
        .scalar_subquery()
    )
    query = update(Card).where(Card.sort_name.is_distinct_from(best)).values(sort_name=best)
    if game_id is not None:
        query = query.where(Card.game_id == game_id)
    if card_ids is not None:
        query = query.where(Card.id.in_(set(card_ids)))
    return query.execution_options(synchronize_session=False)


async def update_sort_names(
    session: AsyncSession, game_id: str | None = None, card_ids: Iterable[int] | None = None
) -> int:
    """Refresh `Card.sort_name` (see `sort_name_query`); returns how many changed."""
    if card_ids is not None:
        card_ids = set(card_ids)
        if not card_ids:
            return 0
    result = await session.execute(sort_name_query(game_id, card_ids))
    return result.rowcount
