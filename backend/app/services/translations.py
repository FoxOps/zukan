"""Latin names for cards known only by non-Latin names.

A card printed only in Japanese, Korean or Chinese sets is shown with a Latin translation
next to its name (see `display`). Sources do not always give one: an Asian set listing a
Trainer by its Japanese name, for instance, while another card of the same game (a joined
international card) has that same Japanese name and an English one. After each catalog
sync the Latin names of such a card are copied to the cards sharing one of its non-Latin
names (Simplified and Traditional Chinese spellings count as the same), when only one card
has that name and both are of the same category.
"""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.games.ocr import chinese_variants
from app.models import Card, CardName
from app.services.scripts import is_latin

_CHUNK = 1000


def _keys(lang: str, name: str) -> list[tuple[str, str]]:
    keys = [(lang, name.casefold())]
    if lang.startswith("zh"):
        keys += [("zh", variant.casefold()) for variant in chinese_variants([name])]
    return keys


async def fill_translations(session: AsyncSession, game_id: str) -> int:
    """Copy Latin card names to cards that have none; returns how many names were added."""
    rows = await session.execute(
        select(CardName.card_id, CardName.lang, CardName.name, Card.attributes["category"].astext)
        .join(Card, Card.id == CardName.card_id)
        .where(Card.game_id == game_id, CardName.printing_id.is_(None))
    )
    names: dict[int, list[tuple[str, str]]] = defaultdict(list)
    category: dict[int, str | None] = {}
    for card_id, lang, name, kind in rows:
        names[card_id].append((lang, name))
        category[card_id] = kind
    latin = {cid: [(lang, n) for lang, n in ns if is_latin(lang)] for cid, ns in names.items()}
    donors: dict[tuple[str, str], set[int]] = defaultdict(set)
    for card_id, ns in names.items():
        if latin[card_id]:
            for lang, name in ns:
                if not is_latin(lang):
                    for key in _keys(lang, name):
                        donors[key].add(card_id)
    added = []
    for card_id, ns in names.items():
        if latin[card_id]:
            continue
        found = {
            donor
            for lang, name in ns
            for key in _keys(lang, name)
            for donor in donors.get(key, ())
            if category.get(donor) == category.get(card_id)
        }
        if len(found) != 1:
            continue
        (donor,) = found
        added += [
            {"card_id": card_id, "printing_id": None, "lang": lang, "name": name}
            for lang, name in latin[donor]
        ]
    for start in range(0, len(added), _CHUNK):
        await session.execute(
            insert(CardName).values(added[start : start + _CHUNK]).on_conflict_do_nothing()
        )
    return len(added)
