"""Plain-text decklists ("4 Lightning Bolt"), as exported by most deck sites and MTG
Arena / MTGO: sections given by header lines ("Commander", "Deck", "Sideboard",
"SB: 2 Duress"), set and collector number suffixes ("(M10) 146", "[M10]") naming the
printing a line asks for (`resolve_printings`; unknown ones leave it at any printing).
Pokémon: Pokémon TCG Live and Limitless exports ("Pokémon: 12", "4 Charmander PAF 7",
"Basic {R} Energy"). Lorcana: Dreamborn / Inktable lists ("4 Elsa - Snow Queen").
Riftbound: "Legend:" / "Champion:" / "Main Deck:" / "Battlefields:" / "Runes:" blocks.
Yu-Gi-Oh!: YDK files ("#main" / "#extra" / "!side", one password per line) and
"Main Deck:" / "Extra Deck:" / "Side Deck:" lists. Sorcery (Curiosa): "Avatar" / "Atlas"
/ "Spellbook" / "Collection" blocks."""

import re
from dataclasses import dataclass, field

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.games.base import registry
from app.models import Card, CardName, CardSet, Printing
from app.services.deck_rules import Section

MAX_LINES = 600
MAX_QUANTITY = 250

_HEADERS: dict[str, Section | None] = {
    "commander": "commander",
    "commanders": "commander",
    "deck": "main",
    "main": "main",
    "maindeck": "main",
    "main deck": "main",
    "mainboard": "main",
    "sideboard": "sideboard",
    "side": "sideboard",
    "companion": "sideboard",
    # Cards being considered: not part of the deck.
    # Riftbound.
    "legend": "legend",
    "champion": "champion",
    "chosen champion": "champion",
    "battlefield": "battlefields",
    "battlefields": "battlefields",
    "rune": "runes",
    "runes": "runes",
    "rune deck": "runes",
    "units": "main",
    "gear": "main",
    # Yu-Gi-Oh! ("#main", "#extra", "!side" in YDK files).
    "extra": "extra",
    "extra deck": "extra",
    "side deck": "sideboard",
    # Sorcery: the spellbook is the main deck, the collection its sideboard.
    "avatar": "avatar",
    "atlas": "atlas",
    "sites": "atlas",
    "spellbook": "main",
    "spells": "main",
    "collection": "sideboard",
    "maybeboard": None,
    "maybe": None,
    "considering": None,
    "tokens": None,
    # Pokémon TCG Live: card kinds, all in the deck.
    "pokemon": "main",
    "pokémon": "main",
    "trainer": "main",
    "trainers": "main",
    "energy": "main",
    "energies": "main",
}
# Header lines that change nothing ("Total Cards: 60").
_IGNORED = {"total cards", "total"}
# "Sideboard", "Sideboard (15)", "Pokémon: 12".
_HEADER = re.compile(
    r"^(?://|#)?\s*([^\W\d_][^\W\d]*(?: [^\W\d_][^\W\d]*)*?)\s*(?:\(\d+\))?\s*(?::\s*\d*)?\s*$"
)
_LINE = re.compile(r"^(?:(\d+)\s*x?\s+)?(.+)$", re.IGNORECASE)
_SUFFIXES = (
    re.compile(r"\s+\*[^*]+\*\s*$"),  # *CMDR*, *F*
    re.compile(r"\s+\^[^^]*\^\s*$"),  # Archidekt tags ^Ramp^
    re.compile(r"\s+#\S.*$"),  # tags
)
# Set code and collector number: "(M10) 146", "(M10)", "[M10]" (or an Archidekt
# "[Category]", then no set of that code is found).
_SET_SUFFIXES = (
    re.compile(r"\s+\[(?P<set>[^\]]+)\]\s*$"),
    re.compile(r"\s+\((?P<set>[A-Za-z0-9]{2,6})\)(?:\s+(?P<number>\S+))?\s*$"),
)
# Pokémon set code and collector number: "PAF 7", "PR-SV 12", "SVP 085", "CRZ GG05".
_POKEMON_SUFFIX = re.compile(
    r"\s+(?P<set>[A-Z][A-Za-z0-9]{1,4}(?:-[A-Z0-9]{1,4})?)\s+(?P<number>[A-Z]{0,3}\d+[a-z]?)\s*$"
)
# Pokémon TCG Live energy symbols ("Basic {R} Energy").
_ENERGY_SYMBOLS = {
    "G": "Grass",
    "R": "Fire",
    "W": "Water",
    "L": "Lightning",
    "P": "Psychic",
    "F": "Fighting",
    "D": "Darkness",
    "M": "Metal",
    "Y": "Fairy",
}
# Layouts that are not deck cards (tokens, art cards).
_NOT_DECK = ("token", "double_faced_token", "art_series", "emblem")


@dataclass
class Line:
    number: int
    text: str
    quantity: int
    name: str
    section: Section
    # The printing named after the card ("(M10) 146"), None: any.
    set_code: str | None = None
    collector_number: str | None = None


@dataclass
class Parsed:
    lines: list[Line] = field(default_factory=list)
    # Line numbers and text that are neither headers nor cards.
    errors: list[tuple[int, str, str]] = field(default_factory=list)


@dataclass
class Cleaned:
    name: str
    commander: bool
    set_code: str | None = None
    collector_number: str | None = None


def _clean_name(name: str, pokemon: bool = False) -> Cleaned:
    """Name without set / tag suffixes, whether it was marked as commander, and the set
    code and collector number it names."""
    found = Cleaned(name, "*cmdr*" in name.lower())
    set_suffixes = (*_SET_SUFFIXES, _POKEMON_SUFFIX) if pokemon else _SET_SUFFIXES
    if pokemon:
        name = re.sub(r"\{([A-Z])\}", lambda m: _ENERGY_SYMBOLS.get(m.group(1), m.group(0)), name)
    changed = True
    while changed:
        changed = False
        for suffix in _SUFFIXES:
            stripped = suffix.sub("", name)
            if stripped != name:
                name, changed = stripped, True
        for suffix in set_suffixes:
            if match := suffix.search(name):
                name, changed = name[: match.start()], True
                if found.set_code is None:
                    found.set_code = match.group("set").strip()
                    found.collector_number = match.groupdict().get("number")
    found.name = re.sub(r"\s+/{1,2}\s+", " // ", name.strip())
    return found


def parse(text: str, game_id: str = "mtg") -> Parsed:
    parsed = Parsed()
    pokemon = game_id.startswith("pokemon")
    section: Section | None = "main"
    for number, raw in enumerate(text.splitlines()[:MAX_LINES], start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("!"):
            # YDK "!side".
            line = line[1:]
        header = _HEADER.match(line)
        if header and (title := header.group(1).strip().lower()) in _HEADERS:
            section = _HEADERS[title]
            continue
        if header and title in _IGNORED:
            continue
        if line.startswith(("//", "#")) or line.lower().startswith(("name ", "about")):
            continue
        line_section = section
        if line.upper().startswith("SB:"):
            line, line_section = line[3:].strip(), "sideboard"
        found = _LINE.match(line)
        quantity = int(found.group(1)) if found and found.group(1) else 1
        cleaned = _clean_name(found.group(2) if found else line, pokemon)
        if not cleaned.name or not 0 < quantity <= MAX_QUANTITY:
            parsed.errors.append((number, raw, "Not a card line"))
            continue
        if line_section is None:
            continue
        parsed.lines.append(
            Line(
                number,
                raw,
                quantity,
                cleaned.name,
                "commander" if cleaned.commander else line_section,
                cleaned.set_code,
                cleaned.collector_number,
            )
        )
    return parsed


def _number(value: str | None) -> str:
    """Collector number compared without case or leading zeros ("085" is "85")."""
    return (value or "").upper().lstrip("0")


async def resolve_printings(
    session: AsyncSession, game_id: str, wanted: list[tuple[int, str, str | None]]
) -> dict[tuple[int, str, str | None], Printing]:
    """The printing of a card (id) a set code and collector number name: the set's
    printing with that number, or its only printing of the card without a number. Set
    codes also match the game's aliases ("ALP" for Sorcery's Alpha)."""
    if not wanted:
        return {}
    aliases: dict[str, str] = {}
    for code, others in (getattr(registry().get(game_id), "set_aliases", {}) or {}).items():
        for other in others:
            aliases[other.casefold()] = code.casefold()
    rows = await session.execute(
        select(Printing, CardSet.code)
        .join(CardSet, Printing.set_id == CardSet.id)
        .where(Printing.card_id.in_({card_id for card_id, _, _ in wanted}))
    )
    by_card_set: dict[tuple[int, str], list[Printing]] = {}
    for printing, code in rows:
        by_card_set.setdefault((printing.card_id, code.casefold()), []).append(printing)
    result = {}
    for key in wanted:
        card_id, code, number = key
        code = code.casefold()
        printings = by_card_set.get((card_id, aliases.get(code, code)), [])
        if number is not None:
            printings = [p for p in printings if _number(p.collector_number) == _number(number)]
        if len(printings) == 1:
            result[key] = printings[0]
    return result


def _key(name):
    return func.lower(func.f_unaccent(name))


@dataclass
class Match:
    # Matching cards (one: resolved, several: ambiguous, none: unknown) and close names.
    cards: list[Card]
    suggestions: list[Card]


async def resolve(session: AsyncSession, game_id: str, names: list[str]) -> dict[str, Match]:
    """Cards named so (case and accents ignored): full name, front face name, then a
    name in another language. Unknown names get close names as suggestions."""
    wanted = sorted(set(names))
    if not wanted:
        return {}
    keys: dict[str, str] = dict(
        (
            await session.execute(
                text("SELECT n, lower(f_unaccent(n)) FROM unnest(CAST(:names AS text[])) AS n"),
                {"names": wanted},
            )
        ).all()
    )
    by_key: dict[str, list[Card]] = {}
    lookups = [_key(Card.name), _key(func.split_part(Card.name, " // ", 1))]
    if game_id.startswith("yugioh"):
        # YDK files list passwords (the cards' ids), without leading zeros.
        lookups.insert(0, func.ltrim(Card.external_id, "0"))
        keys = {name: key.lstrip("0") if key.isdigit() else key for name, key in keys.items()}
    cards_game = select(Card).where(Card.game_id == game_id)
    found: dict[str, list[Card]] = {}
    remaining = set(keys.values())
    for column in lookups:
        if not remaining:
            break
        rows = await session.execute(
            cards_game.add_columns(column.label("key")).where(column.in_(remaining))
        )
        for card, key in rows:
            by_key.setdefault(key, []).append(card)
        for key in list(remaining):
            if key in by_key:
                found[key] = by_key.pop(key)
                remaining.discard(key)
    if remaining:
        rows = await session.execute(
            cards_game.add_columns(CardName.search_name)
            .join(CardName, CardName.card_id == Card.id)
            .where(CardName.search_name.in_(remaining))
            .distinct()
        )
        for card, key in rows:
            found.setdefault(key, []).append(card)
    result: dict[str, Match] = {}
    for name, key in keys.items():
        cards = list({c.id: c for c in found.get(key, [])}.values())
        playable = [c for c in cards if c.attributes.get("layout") not in _NOT_DECK]
        cards = playable or cards
        suggestions = [] if cards else await _close_names(session, game_id, key)
        result[name] = Match(sorted(cards, key=lambda c: c.name), suggestions)
    return result


async def _close_names(session: AsyncSession, game_id: str, key: str) -> list[Card]:
    similarity = func.max(func.similarity(CardName.search_name, key))
    rows = await session.execute(
        select(Card, similarity)
        .join(CardName, CardName.card_id == Card.id)
        .where(Card.game_id == game_id, CardName.search_name.op("%")(key))
        .group_by(Card.id)
        .order_by(similarity.desc(), Card.name)
        .limit(5)
    )
    return [card for card, _ in rows if card.attributes.get("layout") not in _NOT_DECK]
