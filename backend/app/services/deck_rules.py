"""Format rules of the Decks module: Magic: The Gathering, the Pokémon TCG, Disney
Lorcana, Riftbound, Yu-Gi-Oh! (TCG and OCG) and Sorcery: Contested Realm.

Pure functions over the cards' catalog attributes. Magic (`games.mtg.provider.parse_card`):
`types`, `subtypes`, `oracle_text` (or `faces`), `color_identity`, `legalities`. Pokémon
(`games.pokemon.provider.parse_card`): `category`, `stage`, `energyType`, the colors (its
types), and per printing the rarity and TCGdex's `legal`. Lorcana
(`games.lorcana.provider`): the colors (inks), `legalities` and `max_copies` from
LorcanaJSON. Riftbound (`games.riftbound.provider`): `type`, `supertype`, `domains`, `tags`.
Yu-Gi-Oh! (`games.yugioh.provider`): `frame` (or OCG-only cards' `card_type` and
`classifications`), `banlist`, `tcg_date` / `ocg_date`. Sorcery (`games.sorcery.provider`):
`type`, `category`, `rarity`. Results never block saving a
deck: a draft is shown with its issues. Rules the data cannot settle are listed as not
verified instead of passing silently."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

# Every game's deck sections. Spellbook (Sorcery) is "main", collection "sideboard".
Section = Literal[
    "commander",
    "companion",
    "legend",
    "champion",
    "avatar",
    "main",
    "extra",
    "atlas",
    "battlefields",
    "runes",
    "sideboard",
]
SECTIONS: tuple[Section, ...] = (
    "commander",
    "companion",
    "legend",
    "champion",
    "avatar",
    "main",
    "extra",
    "atlas",
    "battlefields",
    "runes",
    "sideboard",
)
Level = Literal["error", "warning", "info"]


# Who leads a deck with a commander section: "commander" legendary creatures (or "can be
# your commander"), "pauper" any creature (Pauper Commander: printed uncommon, not
# checked), "oathbreaker" a planeswalker with one instant or sorcery as signature spell.
Leader = Literal["commander", "pauper", "oathbreaker"]
Rules = Literal["mtg", "pokemon", "lorcana", "riftbound", "yugioh", "sorcery"]

# Sections of a deck, in the order shown, with their English names.
_MTG_SECTIONS: tuple[tuple[Section, str], ...] = (
    ("commander", "Commander"),
    # One companion card, outside the deck (counted in the sideboard's 15).
    ("companion", "Companion"),
    ("main", "Main deck"),
    ("sideboard", "Sideboard"),
)
_MAIN_ONLY: tuple[tuple[Section, str], ...] = (("main", "Main deck"),)


@dataclass(frozen=True)
class Format:
    # Stored in `Deck.format`, unique across games. Magic: Scryfall's legality key.
    id: str
    name: str
    # Cards in the deck (main deck, with the commanders): exact or minimum size.
    size: int
    exact_size: bool
    sideboard_max: int | None
    copies: int
    commander: bool
    leader: Leader | None = None
    rules: Rules = "mtg"
    # Pokémon: TCGdex's legality key ("standard", "expanded"); Lorcana: the card's
    # `legalities` key ("core", "infinity"); Yu-Gi-Oh!: the ban list ("tcg", "ocg").
    # None: every card legal.
    legality: str | None = None
    sections: tuple[tuple[Section, str], ...] = _MTG_SECTIONS
    # Sections `size` counts (the others are shown apart: sideboard, extra deck...).
    counted: tuple[Section, ...] = ("commander", "main")


def _constructed(id: str, name: str) -> Format:
    return Format(id, name, 60, False, 15, 4, False)


def _led(id: str, name: str, size: int, leader: Leader = "commander") -> Format:
    return Format(id, name, size, True, None, 1, True, leader)


# Formats played outside MTG Arena that Scryfall gives legalities for, in the order
# shown. Arena-only formats (Historic, Timeless, Alchemy, Gladiator, the Brawls), the
# "future" Standard preview and the unknown "tlr" are left out.
FORMATS = {
    f.id: f
    for f in (
        _led("commander", "Commander", 100),
        _constructed("standard", "Standard"),
        _constructed("pioneer", "Pioneer"),
        _constructed("modern", "Modern"),
        _constructed("legacy", "Legacy"),
        _constructed("vintage", "Vintage"),
        _constructed("pauper", "Pauper"),
        _constructed("premodern", "Premodern"),
        _constructed("oldschool", "Old School"),
        _constructed("penny", "Penny Dreadful"),
        _led("duel", "Duel Commander", 100),
        _led("predh", "PreDH", 100),
        _led("paupercommander", "Pauper Commander", 100, "pauper"),
        _led("oathbreaker", "Oathbreaker", 60, "oathbreaker"),
    )
}


def _pokemon(id: str, name: str, legality: str | None, copies: int = 4) -> Format:
    return Format(
        id,
        name,
        60,
        True,
        None,
        copies,
        False,
        rules="pokemon",
        legality=legality,
        sections=_MAIN_ONLY,
    )


# Pokémon formats, for the three markets (international, Asia, China). Gym Leader
# Challenge: the community singleton format on the Expanded card pool.
POKEMON_FORMATS = {
    f.id: f
    for f in (
        _pokemon("pokemon_standard", "Standard", "standard"),
        _pokemon("pokemon_expanded", "Expanded", "expanded"),
        _pokemon("pokemon_unlimited", "Unlimited", None),
        _pokemon("pokemon_glc", "Gym Leader Challenge", "expanded", copies=1),
    )
}


def _lorcana(id: str, name: str, legality: str | None) -> Format:
    return Format(
        id, name, 60, False, None, 4, False, rules="lorcana", legality=legality, sections=_MAIN_ONLY
    )


# Lorcana constructed formats (LorcanaJSON's `allowedInFormats`); Unrestricted: the
# deck building rules without a card pool.
LORCANA_FORMATS = {
    f.id: f
    for f in (
        _lorcana("lorcana_core", "Core Constructed", "core"),
        _lorcana("lorcana_infinity", "Infinity Constructed", "infinity"),
        _lorcana("lorcana_unrestricted", "Unrestricted", None),
    )
}

# Riftbound constructed (core rules 103): a Champion Legend, a chosen champion, a main
# deck of 40 or more (champion included), 12 runes, 3 battlefields; sideboard of 8
# (tournament rules).
RIFTBOUND_FORMATS = {
    "riftbound_constructed": Format(
        "riftbound_constructed",
        "Constructed",
        40,
        False,
        8,
        3,
        False,
        rules="riftbound",
        sections=(
            ("legend", "Legend"),
            ("champion", "Chosen champion"),
            ("main", "Main deck"),
            ("battlefields", "Battlefields"),
            ("runes", "Rune deck"),
            ("sideboard", "Sideboard"),
        ),
        counted=("champion", "main"),
    )
}


def _yugioh(id: str, name: str, legality: str | None) -> Format:
    return Format(
        id,
        name,
        40,
        False,
        15,
        3,
        False,
        rules="yugioh",
        legality=legality,
        sections=(("main", "Main Deck"), ("extra", "Extra Deck"), ("sideboard", "Side Deck")),
        counted=("main",),
    )


# Yu-Gi-Oh! Advanced (the ban list of the game: TCG or OCG), Traditional (forbidden
# cards limited to one) and Unrestricted (deck rules without a ban list).
YUGIOH_FORMATS = {
    f.id: f
    for f in (
        _yugioh("yugioh_advanced", "Advanced", "tcg"),
        _yugioh("yugioh_traditional", "Traditional", "tcg"),
        _yugioh("yugioh_unrestricted", "Unrestricted", None),
    )
}
YUGIOH_OCG_FORMATS = {
    f.id: f
    for f in (
        _yugioh("ocg_advanced", "Advanced", "ocg"),
        _yugioh("ocg_traditional", "Traditional", "ocg"),
        _yugioh("ocg_unrestricted", "Unrestricted", None),
    )
}

# Sorcery constructed (rulebook): an avatar, an atlas of 30 sites or more, a spellbook
# of 60 or more, a 10-card collection; copies by rarity.
SORCERY_FORMATS = {
    "sorcery_constructed": Format(
        "sorcery_constructed",
        "Constructed",
        60,
        False,
        10,
        4,
        False,
        rules="sorcery",
        sections=(
            ("avatar", "Avatar"),
            ("atlas", "Atlas"),
            ("main", "Spellbook"),
            ("sideboard", "Collection"),
        ),
        counted=("main",),
    )
}
GAMES = {
    "mtg": tuple(FORMATS),
    "pokemon": tuple(POKEMON_FORMATS),
    "pokemon-asia": tuple(POKEMON_FORMATS),
    "pokemon-china": tuple(POKEMON_FORMATS),
    "lorcana": tuple(LORCANA_FORMATS),
    "riftbound": tuple(RIFTBOUND_FORMATS),
    "yugioh": tuple(YUGIOH_FORMATS),
    "yugioh-ocg": tuple(YUGIOH_OCG_FORMATS),
    "sorcery": tuple(SORCERY_FORMATS),
}
FORMATS |= (
    POKEMON_FORMATS
    | LORCANA_FORMATS
    | RIFTBOUND_FORMATS
    | YUGIOH_FORMATS
    | YUGIOH_OCG_FORMATS
    | SORCERY_FORMATS
)


@dataclass
class RulePrinting:
    rarity: str | None
    # TCGdex's {"standard": bool, "expanded": bool} (Pokémon), None: not known.
    legal: dict[str, bool] | None = None


@dataclass
class RuleCard:
    card_id: int
    name: str
    attributes: dict[str, Any]
    colors: list[str] = field(default_factory=list)
    # Pokémon only (rarity and legality are per printing).
    printings: list[RulePrinting] = field(default_factory=list)

    @property
    def types(self) -> list[str]:
        return self.attributes.get("types") or []

    @property
    def subtypes(self) -> list[str]:
        return self.attributes.get("subtypes") or []

    @property
    def text(self) -> str:
        """Rules text of every face."""
        faces = self.attributes.get("faces") or []
        texts = [f.get("oracle_text", "") for f in faces] or [
            self.attributes.get("oracle_text", "")
        ]
        return "\n".join(t for t in texts if t)

    @property
    def color_identity(self) -> set[str]:
        return set(self.attributes.get("color_identity") or [])


@dataclass
class Entry:
    card: RuleCard
    section: Section
    quantity: int


@dataclass
class Issue:
    level: Level
    # Stable id the web translates, with `params`; `message` is the English text.
    code: str
    message: str
    card_id: int | None = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    # Checks that could not be made (missing data, rules not modelled).
    unverified: list[Issue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    def add(self, level: Level, code: str, message: str, card: RuleCard | None = None, **params):
        if card is not None:
            params.setdefault("name", card.name)
        self.issues.append(Issue(level, code, message, card.card_id if card else None, params))

    def note(self, code: str, message: str, **params) -> None:
        self.unverified.append(Issue("info", code, message, None, params))


_ANY_NUMBER = "a deck can have any number of cards named"
_UP_TO = re.compile(r"a deck can have up to (\w+) cards named", re.IGNORECASE)
_NUMBERS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}


def is_basic_land(card: RuleCard) -> bool:
    return "Basic" in card.types and "Land" in card.types


def copy_limit(card: RuleCard, fmt: Format) -> int | None:
    """Copies allowed (None: any number)."""
    if is_basic_land(card) or _ANY_NUMBER in card.text.lower():
        return None
    if (found := _UP_TO.search(card.text)) and found.group(1).lower() in _NUMBERS:
        return max(_NUMBERS[found.group(1).lower()], fmt.copies)
    return fmt.copies


def _can_lead(card: RuleCard, leader: Leader = "commander") -> bool:
    if "can be your commander" in card.text.lower():
        return True
    if leader == "pauper":
        return "Creature" in card.types
    return "Legendary" in card.types and "Creature" in card.types


def _partner_kind(text: str) -> str | None:
    """ "Partner", "Partner—Survivors", "Friends forever"... (None: none)."""
    for line in text.splitlines():
        line = line.strip()
        if re.match(r"^Partner(\s*[—-]\s*\S.*)?(\s*\(.*\))?$", line) and not line.startswith(
            "Partner with"
        ):
            return line.split("(")[0].strip()
        if line.lower().startswith("friends forever"):
            return "Friends forever"
    return None


def _pair_ok(first: RuleCard, second: RuleCard) -> bool:
    """Two cards that may lead a deck together (rules text keywords)."""
    for a, b in ((first, second), (second, first)):
        if f"partner with {b.name.split(' // ')[0].lower()}" in a.text.lower():
            return True
        if "choose a background" in a.text.lower() and "Background" in b.subtypes:
            return True
        if "doctor's companion" in a.text.lower() and {"Time", "Lord", "Doctor"} <= set(b.subtypes):
            return True
    kind = _partner_kind(first.text)
    return kind is not None and kind == _partner_kind(second.text)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def legality(card: RuleCard, fmt: Format) -> str:
    """ "legal", "banned", "not_legal", "restricted" or "unknown" (no data)."""
    if fmt.rules == "pokemon":
        if fmt.legality is None:
            return "legal"
        known = [p.legal for p in card.printings if p.legal is not None]
        if not known:
            return "unknown"
        # A card is legal when any of its printings is (reprints share the card's name).
        return "legal" if any(legal.get(fmt.legality) for legal in known) else "not_legal"
    if fmt.rules in ("riftbound", "sorcery"):
        # No ban list in the data.
        return "legal"
    if fmt.rules == "yugioh":
        return yugioh_legality(card, fmt)
    if fmt.rules == "lorcana" and fmt.legality is None:
        return "legal"
    legalities = card.attributes.get("legalities")
    if legalities is None:
        return "unknown"
    return legalities.get(fmt.legality if fmt.rules == "lorcana" else fmt.id, "not_legal")


def check(format_id: str, entries: list[Entry]) -> Report:
    report = Report()
    fmt = FORMATS.get(format_id)
    if fmt is None:
        report.note("unknown_format", f"No rules known for format '{format_id}'", format=format_id)
        return report
    if fmt.rules == "pokemon":
        _check_pokemon(report, fmt, entries)
        return report
    if fmt.rules == "lorcana":
        _check_lorcana(report, fmt, entries)
        return report
    if fmt.rules in _CHECKS:
        _CHECKS[fmt.rules](report, fmt, entries)
        return report
    by_section: dict[str, list[Entry]] = {s: [] for s in SECTIONS}
    for entry in entries:
        by_section[entry.section].append(entry)
    _unused_sections(report, fmt, by_section)
    commanders = by_section["commander"]
    deck_size = sum(e.quantity for e in by_section["main"] + commanders)
    side_size = sum(e.quantity for e in by_section["sideboard"])
    companions = by_section["companion"]
    # Constructed: the companion is one of the sideboard's 15 cards.
    side_total = side_size + (0 if fmt.commander else sum(e.quantity for e in companions))

    # Deck size.
    if fmt.exact_size and deck_size != fmt.size:
        report.add(
            "error",
            "deck_size_exact",
            f"The deck has {_plural(deck_size, 'card')} (commanders included), "
            f"it needs exactly {fmt.size}",
            count=deck_size,
            size=fmt.size,
        )
    elif not fmt.exact_size and deck_size < fmt.size:
        report.add(
            "error",
            "deck_size_min",
            f"The main deck has {_plural(deck_size, 'card')}, it needs at least {fmt.size}",
            count=deck_size,
            size=fmt.size,
        )
    if fmt.sideboard_max is not None and side_total > fmt.sideboard_max:
        report.add(
            "error",
            "sideboard_max",
            f"The sideboard has {_plural(side_total, 'card')}, at most {fmt.sideboard_max} allowed",
            count=side_total,
            size=fmt.sideboard_max,
        )
    if fmt.commander and side_size:
        report.add(
            "info",
            "sideboard_ignored",
            f"{fmt.name} has no sideboard: {_plural(side_size, 'card')} not counted",
            count=side_size,
        )
    if not fmt.commander and commanders:
        report.add(
            "warning",
            "commander_unused",
            f"{fmt.name} has no commander: those cards count as main deck",
        )

    # Copies of each card across sections (sideboard and companion included, as in
    # tournaments; commander formats: the deck only).
    copies: dict[int, int] = {}
    cards: dict[int, RuleCard] = {}
    for entry in entries:
        if fmt.commander and entry.section in ("sideboard", "companion"):
            continue
        copies[entry.card.card_id] = copies.get(entry.card.card_id, 0) + entry.quantity
        cards[entry.card.card_id] = entry.card
    for card_id, count in copies.items():
        card = cards[card_id]
        limit = copy_limit(card, fmt)
        if limit is not None and count > limit:
            report.add(
                "error",
                "copy_limit",
                f"{card.name}: {count} copies, at most {limit} allowed",
                card,
                count=count,
                limit=limit,
            )

    # Legality. Pauper Commander's commanders are uncommons, not legal in the deck itself
    # (their rarity is not in the card data: not checked).
    leading: set[int] = set()
    if fmt.leader == "pauper":
        leading = {e.card.card_id for e in commanders}
        report.note("commander_rarity", "Commanders printed at uncommon are not checked")
    unknown = []
    # The companion must be legal too.
    for card in [*cards.values(), *(e.card for e in companions if e.card.card_id not in cards)]:
        if card.card_id in leading:
            continue
        status = legality(card, fmt)
        if status == "unknown":
            unknown.append(card.name)
            continue
        if status == "banned":
            report.add("error", "banned", f"{card.name} is banned in {fmt.name}", card)
        elif status == "not_legal":
            report.add("error", "not_legal", f"{card.name} is not legal in {fmt.name}", card)
        elif status == "restricted" and copies.get(card.card_id, 1) > 1:
            report.add(
                "error", "restricted", f"{card.name} is restricted to one copy", card, limit=1
            )
    if unknown:
        report.note(
            "legality_unknown",
            f"Legality of {_plural(len(unknown), 'card')} not known (sync the Magic catalog "
            "again): " + ", ".join(sorted(unknown)[:10]) + ("…" if len(unknown) > 10 else ""),
            count=len(unknown),
            names=sorted(unknown),
        )

    if fmt.leader == "oathbreaker":
        _check_oathbreaker(report, commanders, by_section["main"])
    elif fmt.leader is not None:
        _check_commanders(report, fmt.leader, commanders, by_section["main"])
    _check_companions(report, fmt, commanders, by_section["main"], companions)
    report.note("not_modelled", "Not checked: cards with other special deck rules")
    return report


# Companions (Ikoria), put in the Companion section, each with a condition on the starting
# deck (main deck and commanders), by front face name.
COMPANIONS = {
    "Gyruda, Doom of Depths": "gyruda",
    "Jegantha, the Wellspring": "jegantha",
    "Kaheera, the Orphanguard": "kaheera",
    "Keruga, the Macrosage": "keruga",
    "Lurrus of the Dream-Den": "lurrus",
    "Lutri, the Spellchaser": "lutri",
    "Obosh, the Preypiercer": "obosh",
    "Umori, the Collector": "umori",
    "Yorion, Sky Nomad": "yorion",
    "Zirda, the Dawnwaker": "zirda",
}
# English text of each condition (the web translates the rule id).
COMPANION_RULES = {
    "gyruda": "every nonland card needs an even mana value",
    "jegantha": "no card may have the same mana symbol twice in its cost",
    "kaheera": "every creature must be a Cat, Elemental, Nightmare, Dinosaur or Beast",
    "keruga": "every nonland card needs a mana value of 3 or more",
    "lurrus": "every permanent card needs a mana value of 2 or less",
    "lutri": "every nonland card needs a different name",
    "obosh": "every nonland card needs an odd mana value",
    "umori": "every nonland card must share a card type",
    "yorion": "the deck needs at least 20 cards more than the minimum",
    "zirda": "every permanent card needs an activated ability",
}
_PERMANENT = {"Artifact", "Battle", "Creature", "Enchantment", "Land", "Planeswalker"}
_CARD_TYPES = _PERMANENT | {"Instant", "Sorcery", "Kindred", "Tribal"}
_KAHEERA = {"Cat", "Elemental", "Nightmare", "Dinosaur", "Beast"}
_BASIC_LAND_TYPES = {"Plains", "Island", "Swamp", "Mountain", "Forest"}
_QUOTED = re.compile(r'"[^"]*"')


def _front(card: RuleCard) -> dict[str, Any]:
    """Characteristics in the library: both halves of split cards, else the front face
    (modal double-faced, transforming, adventure and flip cards)."""
    faces = card.attributes.get("faces") or []
    if not faces or card.attributes.get("layout") == "split":
        return {"types": card.types, "subtypes": card.subtypes, "text": card.text}
    face = faces[0]
    left, _, right = (face.get("type_line") or "").partition("—")
    return {
        "types": left.split() or card.types,
        "subtypes": right.split(),
        "text": face.get("oracle_text", ""),
        "mana_cost": face.get("mana_cost"),
    }


def _mana_cost(card: RuleCard) -> str:
    """Mana cost in the library: both halves of split cards, else the front face."""
    if card.attributes.get("faces") and card.attributes.get("layout") != "split":
        return _front(card).get("mana_cost") or ""
    return card.attributes.get("mana_cost") or ""


def _has_activated_ability(card: RuleCard, front: dict[str, Any]) -> bool:
    """From rules text: a colon outside quoted abilities given to other objects (keyword
    reminder text included); basic land types have their mana ability."""
    if _BASIC_LAND_TYPES & set(front["subtypes"]):
        return True
    return any(":" in _QUOTED.sub("", line) for line in front["text"].splitlines())


def _companion_misses(rule: str, deck: list[Entry]) -> tuple[list[str], bool]:
    """Starting deck cards breaking a companion's condition (empty: met), and whether a
    mana value was unknown (those cards are skipped). Not for Yorion (deck size)."""
    misses: list[str] = []
    unknown = False
    counts: dict[int, int] = {}
    for entry in deck:
        counts[entry.card.card_id] = counts.get(entry.card.card_id, 0) + entry.quantity
    shared: set[str] | None = None
    seen: set[int] = set()
    for entry in deck:
        card = entry.card
        if card.card_id in seen:
            continue
        seen.add(card.card_id)
        front = _front(card)
        types = set(front["types"])
        land, permanent = "Land" in types, bool(_PERMANENT & types)
        value = card.attributes.get("cmc")
        needs_value = (rule in ("gyruda", "keruga", "obosh") and not land) or (
            rule == "lurrus" and permanent
        )
        if needs_value and value is None:
            unknown = True
            continue
        broken = False
        if rule == "gyruda":
            broken = not land and int(value) % 2 == 1
        elif rule == "obosh":
            broken = not land and int(value) % 2 == 0
        elif rule == "keruga":
            broken = not land and value < 3
        elif rule == "lurrus":
            broken = permanent and value > 2
        elif rule == "jegantha":
            symbols = re.findall(r"\{[^}]+\}", _mana_cost(card))
            broken = len(symbols) != len(set(symbols))
        elif rule == "kaheera":
            broken = (
                "Creature" in types
                and not _KAHEERA & set(front["subtypes"])
                and "changeling" not in front["text"].lower()
            )
        elif rule == "lutri":
            broken = not land and counts[card.card_id] > 1
        elif rule == "zirda":
            broken = permanent and not _has_activated_ability(card, front)
        elif rule == "umori" and not land:
            kinds = types & _CARD_TYPES
            shared = kinds if shared is None else shared & kinds
        if broken:
            misses.append(card.name)
    if rule == "umori" and shared is not None and not shared:
        misses = sorted({e.card.name for e in deck if "Land" not in _front(e.card)["types"]})
    return sorted(misses), unknown


def _check_companions(
    report: Report,
    fmt: Format,
    commanders: list[Entry],
    main: list[Entry],
    companions: list[Entry],
) -> None:
    """The card in the Companion section: one at most, a companion, its condition met by
    the starting deck (main deck and commanders), and in commander formats within the
    commanders' color identity. Companion cards elsewhere (sideboard, main deck) are
    ordinary cards."""
    count = sum(e.quantity for e in companions)
    if count > 1:
        report.add("error", "companion_count", f"{count} companions, at most 1", count=count)
    deck = commanders + main
    for entry in companions:
        card = entry.card
        rule = COMPANIONS.get(card.name.split(" // ")[0])
        if rule is None:
            if "companion —" in card.text.lower():
                report.note(
                    "companion_unknown",
                    f"{card.name}: companion condition not checked",
                    name=card.name,
                )
            else:
                report.add("error", "not_companion", f"{card.name} is not a companion", card)
            continue
        misses: list[str] = []
        size = None
        if rule == "yorion":
            # Never met where the size is exact (Commander's 100).
            if not fmt.exact_size and sum(e.quantity for e in deck) >= fmt.size + 20:
                continue
            size = None if fmt.exact_size else fmt.size + 20
        else:
            misses, unknown = _companion_misses(rule, deck)
            if rule == "zirda":
                report.note(
                    "zirda_by_text", "Activated abilities (Zirda) are checked from rules text"
                )
            if unknown:
                report.note(
                    "companion_value_unknown",
                    f"{card.name}: mana value of some cards not known (sync the Magic catalog "
                    "again)",
                    name=card.name,
                )
            if not misses:
                continue
        report.add(
            "error",
            "companion",
            f"{card.name} cannot be your companion: {COMPANION_RULES[rule]}"
            + (f" ({', '.join(misses[:5])}{'…' if len(misses) > 5 else ''})" if misses else ""),
            card,
            rule=rule,
            names=misses,
            **({"size": size} if size else {}),
        )
    if fmt.commander and commanders:
        identity = set().union(*(e.card.color_identity for e in commanders))
        _check_identity(report, identity, companions)


def _check_commanders(
    report: Report, leader: Leader, commanders: list[Entry], main: list[Entry]
) -> None:
    leaders = [e.card for e in commanders for _ in range(e.quantity)]
    if not leaders:
        report.add("error", "no_commander", "Choose a commander")
        report.note("color_identity_unchecked", "Color identity is checked once a commander is set")
        return
    if len(leaders) > 2:
        report.add(
            "error",
            "too_many_commanders",
            f"{len(leaders)} commanders, at most 2 allowed",
            count=len(leaders),
        )
    elif len(leaders) == 2:
        first, second = leaders
        if first.card_id == second.card_id or not _pair_ok(first, second):
            report.add(
                "error",
                "commander_pair",
                f"{first.name} and {second.name} cannot lead a deck together",
            )
        report.note(
            "pair_by_text",
            "Commander pairs (Partner, Friends forever, Background, Doctor's companion) are "
            "checked from rules text",
        )
    backgrounds_allowed = any("choose a background" in c.text.lower() for c in leaders)
    for card in leaders:
        if _can_lead(card, leader) or (backgrounds_allowed and "Background" in card.subtypes):
            continue
        if leader == "pauper":
            report.add(
                "error", "invalid_commander_creature", f"{card.name} is not a creature", card
            )
        else:
            report.add(
                "error",
                "invalid_commander",
                f"{card.name} cannot be a commander (not a legendary creature)",
                card,
            )
    _check_identity(report, set().union(*(c.color_identity for c in leaders)), main)


def _is_spell(card: RuleCard) -> bool:
    return "Instant" in card.types or "Sorcery" in card.types


def _check_oathbreaker(report: Report, commanders: list[Entry], main: list[Entry]) -> None:
    """Oathbreaker: a planeswalker (two with partner) leads, each with one instant or
    sorcery of its colors as signature spell, all in the commander section."""
    cards = [e.card for e in commanders for _ in range(e.quantity)]
    walkers = [c for c in cards if "Planeswalker" in c.types]
    spells = [c for c in cards if "Planeswalker" not in c.types and _is_spell(c)]
    for entry in commanders:
        if "Planeswalker" not in entry.card.types and not _is_spell(entry.card):
            report.add(
                "error",
                "invalid_oathbreaker",
                f"{entry.card.name} is neither a planeswalker nor an instant or sorcery",
                entry.card,
            )
    if not walkers:
        report.add("error", "no_oathbreaker", "Choose an oathbreaker (a planeswalker)")
        report.note("color_identity_unchecked", "Color identity is checked once a commander is set")
        return
    if len(walkers) > 2 or (
        len(walkers) == 2 and (walkers[0].card_id == walkers[1].card_id or not _pair_ok(*walkers))
    ):
        report.add(
            "error",
            "too_many_oathbreakers",
            f"{len(walkers)} oathbreakers: one, or two with partner",
            count=len(walkers),
        )
    if len(spells) != len(walkers):
        report.add(
            "error",
            "signature_spells",
            f"{_plural(len(spells), 'signature spell')} for "
            f"{_plural(len(walkers), 'oathbreaker')}: one instant or sorcery each",
            count=len(spells),
            size=len(walkers),
        )
    identity = set().union(*(c.color_identity for c in walkers))
    _check_identity(report, identity, [e for e in commanders if e.card in spells] + main)


def _check_identity(report: Report, identity: set[str], main: list[Entry]) -> None:
    for entry in main:
        outside = entry.card.color_identity - identity
        if outside:
            colors = "".join(c for c in "WUBRG" if c in outside)
            report.add(
                "error",
                "color_identity",
                f"{entry.card.name} is outside the commander's color identity ({colors})",
                entry.card,
                colors=colors,
            )


# Pokémon card kinds. Category, stage and energy type are TCGdex's English values (a few
# cards keep their French ones); Asian names are matched too.
_BASIC_ENERGY = re.compile(
    r"^(basic )?(grass|fire|water|lightning|psychic|fighting|darkness|metal|fairy) energy$"
    r"|基本|기본",
    re.IGNORECASE,
)
_RULE_BOX = re.compile(
    r"(\s|-)(ex|EX|GX|V|VMAX|VSTAR|V-UNION|BREAK|LEGEND)\b|◇|★|^(Radiant|M|Mega) |^かがやく"
)
_RULE_BOX_STAGES = {"VMAX", "VSTAR", "V-UNION", "BREAK", "LEGEND", "MEGA"}


def _category(card: RuleCard) -> str | None:
    category = card.attributes.get("category")
    return "Pokemon" if category == "Pokémon" else category


def is_basic_energy(card: RuleCard) -> bool:
    if _category(card) != "Energy":
        return False
    kind = card.attributes.get("energyType")
    return kind == "Normal" or (kind is None and bool(_BASIC_ENERGY.search(card.name)))


def is_basic_pokemon(card: RuleCard) -> bool:
    return _category(card) == "Pokemon" and card.attributes.get("stage") in ("Basic", "Base")


def is_ace_spec(card: RuleCard) -> bool:
    return any(p.rarity and "ACE" in p.rarity.upper() for p in card.printings)


def is_radiant(card: RuleCard) -> bool:
    return card.name.startswith(("Radiant ", "かがやく")) or any(
        p.rarity and "Radiant" in p.rarity for p in card.printings
    )


def is_prism_star(card: RuleCard) -> bool:
    return "◇" in card.name


def has_rule_box(card: RuleCard) -> bool:
    """Pokémon ex, EX, GX, V, VMAX, VSTAR, Radiant, Prism Star, BREAK, LEGEND..."""
    if _category(card) != "Pokemon":
        return False
    return bool(_RULE_BOX.search(card.name)) or card.attributes.get("stage") in _RULE_BOX_STAGES


def _check_pokemon(report: Report, fmt: Format, entries: list[Entry]) -> None:
    main = [e for e in entries if e.section == "main"]
    others = sum(e.quantity for e in entries if e.section != "main")
    deck_size = sum(e.quantity for e in main)
    if deck_size != fmt.size:
        report.add(
            "error",
            "deck_size",
            f"The deck has {_plural(deck_size, 'card')}, it needs exactly {fmt.size}",
            count=deck_size,
            size=fmt.size,
        )
    if others:
        report.add(
            "info",
            "section_unused",
            f"{fmt.name} decks have no sideboard nor commander: "
            f"{_plural(others, 'card')} not counted",
            count=others,
        )

    copies: dict[int, int] = {}
    cards: dict[int, RuleCard] = {}
    for entry in main:
        copies[entry.card.card_id] = copies.get(entry.card.card_id, 0) + entry.quantity
        cards[entry.card.card_id] = entry.card
    # Copies by name: the catalog has one card per name (and language).
    for card_id, count in copies.items():
        card = cards[card_id]
        limit = 1 if is_prism_star(card) else fmt.copies
        if not is_basic_energy(card) and count > limit:
            report.add(
                "error",
                "copy_limit",
                f"{card.name}: {count} copies, at most {limit} allowed",
                card,
                count=count,
                limit=limit,
            )

    if main and not any(is_basic_pokemon(c) for c in cards.values()):
        if any(_category(c) == "Pokemon" and not c.attributes.get("stage") for c in cards.values()):
            report.note("basic_unknown", "The stage of some Pokémon is not known")
        else:
            report.add("error", "no_basic", "The deck needs at least one Basic Pokémon")

    glc = fmt.copies == 1
    ace_specs = [c for c in cards.values() if is_ace_spec(c)]
    if glc:
        for card in ace_specs:
            report.add("error", "ace_spec_banned", f"{card.name}: ACE SPEC cards are banned", card)
    elif (count := sum(copies[c.card_id] for c in ace_specs)) > 1:
        report.add(
            "error",
            "ace_spec_max",
            f"{_plural(count, 'ACE SPEC card')}, at most 1 allowed",
            count=count,
        )
    radiants = sum(copies[c.card_id] for c in cards.values() if is_radiant(c))
    if radiants > 1 and not glc:
        report.add(
            "error",
            "radiant_max",
            f"{radiants} Radiant Pokémon, at most 1 allowed",
            count=radiants,
        )
    if glc:
        _check_glc(report, [c for c in cards.values() if _category(c) == "Pokemon"], copies)

    if fmt.legality is not None:
        unknown = []
        for card in cards.values():
            status = legality(card, fmt)
            if status == "unknown":
                unknown.append(card.name)
            elif status == "not_legal":
                report.add("error", "not_legal", f"{card.name} is not legal in {fmt.name}", card)
        if unknown:
            report.note(
                "legality_unknown",
                f"Legality of {_plural(len(unknown), 'card')} not known (sync the Pokémon "
                "catalog again; Asian and Chinese cards have none): "
                + ", ".join(sorted(unknown)[:10])
                + ("…" if len(unknown) > 10 else ""),
                count=len(unknown),
                names=sorted(unknown),
            )
    report.note("special_rules", "Not checked: cards with special deck rules")


def _check_glc(report: Report, pokemon: list[RuleCard], copies: dict[int, int]) -> None:
    """Gym Leader Challenge: no Rule Box Pokémon, every Pokémon of one shared type."""
    for card in pokemon:
        if has_rule_box(card):
            report.add("error", "rule_box", f"{card.name}: Rule Box Pokémon are banned", card)
    if pokemon and not set.intersection(*(set(c.colors) for c in pokemon)):
        # The type most copies have is the deck's; the others are off type.
        counts: dict[str, int] = {}
        for card in pokemon:
            for color in card.colors:
                counts[color] = counts.get(color, 0) + copies[card.card_id]
        main_type = max(counts, key=lambda c: counts[c]) if counts else ""
        for card in pokemon:
            if main_type not in card.colors:
                report.add(
                    "error",
                    "single_type",
                    f"{card.name} is not of the deck's type ({main_type})",
                    card,
                    type=main_type,
                )
    report.note("glc_bans", "Not checked: the Gym Leader Challenge ban list")


def lorcana_copy_limit(card: RuleCard, fmt: Format) -> int | None:
    """Copies allowed (None: any number): the card's own limit, else the format's."""
    limit = card.attributes.get("max_copies")
    if limit == "any":
        return None
    return limit if isinstance(limit, int) else fmt.copies


def _check_lorcana(report: Report, fmt: Format, entries: list[Entry]) -> None:
    """60 cards or more, 4 copies of a full name (name and version), one or two inks."""
    main = [e for e in entries if e.section == "main"]
    others = sum(e.quantity for e in entries if e.section != "main")
    deck_size = sum(e.quantity for e in main)
    if deck_size < fmt.size:
        report.add(
            "error",
            "deck_size_min",
            f"The deck has {_plural(deck_size, 'card')}, it needs at least {fmt.size}",
            count=deck_size,
            size=fmt.size,
        )
    if others:
        report.add(
            "info",
            "section_unused",
            f"{fmt.name} decks have no sideboard nor commander: "
            f"{_plural(others, 'card')} not counted",
            count=others,
        )

    copies: dict[int, int] = {}
    cards: dict[int, RuleCard] = {}
    for entry in main:
        copies[entry.card.card_id] = copies.get(entry.card.card_id, 0) + entry.quantity
        cards[entry.card.card_id] = entry.card
    for card_id, count in copies.items():
        card = cards[card_id]
        limit = lorcana_copy_limit(card, fmt)
        if limit is not None and count > limit:
            report.add(
                "error",
                "copy_limit",
                f"{card.name}: {count} copies, at most {limit} allowed",
                card,
                count=count,
                limit=limit,
            )

    # Inks: at most two; a dual-ink card brings both of its inks.
    inks: dict[str, int] = {}
    for card in cards.values():
        for ink in card.colors:
            inks[ink] = inks.get(ink, 0) + copies[card.card_id]
    if len(inks) > 2:
        # The two inks most copies have are the deck's; cards of the others are off ink.
        kept = sorted(inks, key=lambda ink: (-inks[ink], ink))[:2]
        report.add(
            "error",
            "inks_max",
            f"The deck has {len(inks)} inks ({', '.join(sorted(inks))}), at most 2 allowed",
            count=len(inks),
            inks=sorted(inks),
        )
        for card in cards.values():
            if not set(card.colors) <= set(kept):
                report.add(
                    "error",
                    "off_ink",
                    f"{card.name} is not of the deck's inks ({', '.join(sorted(kept))})",
                    card,
                    inks=sorted(kept),
                )

    if fmt.legality is not None:
        unknown = []
        for card in cards.values():
            status = legality(card, fmt)
            if status == "unknown":
                unknown.append(card.name)
            elif status == "banned":
                report.add("error", "banned", f"{card.name} is banned in {fmt.name}", card)
            elif status == "not_legal":
                report.add("error", "not_legal", f"{card.name} is not legal in {fmt.name}", card)
        if unknown:
            report.note(
                "legality_unknown",
                f"Legality of {_plural(len(unknown), 'card')} not known (sync the Lorcana "
                "catalog again): "
                + ", ".join(sorted(unknown)[:10])
                + ("…" if len(unknown) > 10 else ""),
                count=len(unknown),
                names=sorted(unknown),
            )


def _by_section(entries: list[Entry]) -> dict[str, list[Entry]]:
    found: dict[str, list[Entry]] = {s: [] for s in SECTIONS}
    for entry in entries:
        found[entry.section].append(entry)
    return found


def _count(entries: list[Entry]) -> int:
    return sum(e.quantity for e in entries)


def _copies(entries: list[Entry]) -> tuple[dict[int, int], dict[int, RuleCard]]:
    """Copies of each card across the given lines (one card per name in these games)."""
    copies: dict[int, int] = {}
    cards: dict[int, RuleCard] = {}
    for entry in entries:
        copies[entry.card.card_id] = copies.get(entry.card.card_id, 0) + entry.quantity
        cards[entry.card.card_id] = entry.card
    return copies, cards


def _unused_sections(report: Report, fmt: Format, by_section: dict[str, list[Entry]]) -> None:
    names = dict(fmt.sections)
    others = sum(_count(lines) for section, lines in by_section.items() if section not in names)
    if others:
        report.add(
            "info",
            "section_unused",
            f"{fmt.name} decks have no such section: {_plural(others, 'card')} not counted",
            count=others,
        )


def _size(
    report: Report,
    fmt: Format,
    section: Section,
    count: int,
    minimum: int | None = None,
    maximum: int | None = None,
    level: Level = "error",
) -> None:
    """Size of one section: exact when `minimum == maximum`."""
    name = dict(fmt.sections)[section]
    if minimum is not None and minimum == maximum:
        if count != minimum:
            report.add(
                level,
                "section_size_exact",
                f"{name}: {_plural(count, 'card')}, it needs exactly {minimum}",
                section=name,
                count=count,
                size=minimum,
            )
        return
    if minimum is not None and count < minimum:
        report.add(
            level,
            "section_size_min",
            f"{name}: {_plural(count, 'card')}, it needs at least {minimum}",
            section=name,
            count=count,
            size=minimum,
        )
    if maximum is not None and count > maximum:
        report.add(
            level,
            "section_size_max",
            f"{name}: {_plural(count, 'card')}, at most {maximum} allowed",
            section=name,
            count=count,
            size=maximum,
        )


def _wrong_section(report: Report, fmt: Format, entry: Entry) -> None:
    name = dict(fmt.sections).get(entry.section, entry.section)
    report.add(
        "error",
        "wrong_section",
        f"{entry.card.name} cannot be in the {name}",
        entry.card,
        section=name,
    )


def _copy_limits(
    report: Report,
    copies: dict[int, int],
    cards: dict[int, RuleCard],
    limit_of: Callable[[RuleCard], int | None],
) -> None:
    for card_id, count in copies.items():
        card = cards[card_id]
        limit = limit_of(card)
        if limit is not None and count > limit:
            report.add(
                "error",
                "copy_limit",
                f"{card.name}: {count} copies, at most {limit} allowed",
                card,
                count=count,
                limit=limit,
            )


# Riftbound: card kinds (`type`: Legend, Unit, Spell, Gear, Rune, Battlefield),
# champion units (`supertype`, missing from some sources).
def rb_type(card: RuleCard) -> str | None:
    return card.attributes.get("type")


def _rb_domains(card: RuleCard) -> set[str]:
    """The card's domains; colorless cards (some sources list "colorless") fit any."""
    return {d.lower() for d in card.attributes.get("domains") or []} - {"colorless"}


_RB_KINDS: dict[Section, str] = {"legend": "Legend", "runes": "Rune", "battlefields": "Battlefield"}


def _check_riftbound(report: Report, fmt: Format, entries: list[Entry]) -> None:
    by_section = _by_section(entries)
    _unused_sections(report, fmt, by_section)
    legends = [e.card for e in by_section["legend"] for _ in range(e.quantity)]
    champions = [e.card for e in by_section["champion"] for _ in range(e.quantity)]
    deck = by_section["champion"] + by_section["main"]
    _size(report, fmt, "legend", len(legends), 1, 1)
    _size(report, fmt, "champion", len(champions), 1, 1)
    _size(report, fmt, "main", _count(deck), fmt.size)
    _size(report, fmt, "runes", _count(by_section["runes"]), 12, 12)
    _size(report, fmt, "battlefields", _count(by_section["battlefields"]), 3, 3)
    _size(report, fmt, "sideboard", _count(by_section["sideboard"]), maximum=fmt.sideboard_max)

    # Card kinds of each section.
    for section, kind in _RB_KINDS.items():
        for entry in by_section[section]:
            if rb_type(entry.card) != kind:
                _wrong_section(report, fmt, entry)
    for entry in deck + by_section["sideboard"]:
        if rb_type(entry.card) in _RB_KINDS.values():
            _wrong_section(report, fmt, entry)

    # The chosen champion: a champion unit with the legend's champion tag (its first).
    legend = legends[0] if legends else None
    tag = next(iter(legend.attributes.get("tags") or []), None) if legend else None
    for card in champions:
        if rb_type(card) != "Unit" or card.attributes.get("supertype") not in (None, "Champion"):
            report.add("error", "invalid_champion", f"{card.name} is not a champion unit", card)
        elif tag and tag not in (card.attributes.get("tags") or []):
            report.add(
                "error", "champion_tag", f"{card.name} is not a {tag} champion", card, tag=tag
            )

    # Three copies of a name (sideboard included), battlefields of different names.
    copies, cards = _copies(deck + by_section["sideboard"])
    _copy_limits(report, copies, cards, lambda _: fmt.copies)
    for entry in by_section["battlefields"]:
        if entry.quantity > 1:
            report.add(
                "error",
                "battlefield_duplicate",
                f"{entry.card.name}: one battlefield of each name",
                entry.card,
            )
    signatures = sum(
        copies[c.card_id] for c in cards.values() if c.attributes.get("supertype") == "Signature"
    )
    if signatures > 3:
        report.add(
            "error",
            "signature_max",
            f"{signatures} Signature cards, at most 3 allowed",
            count=signatures,
        )

    # Domain identity: the legend's domains (cards of no domain fit any).
    if legend is None:
        report.note("domains_unchecked", "Domains are checked once a legend is set")
    else:
        identity = _rb_domains(legend)
        others = by_section["runes"] + by_section["battlefields"] + by_section["sideboard"]
        for entry in deck + others:
            if _rb_domains(entry.card) - identity:
                report.add(
                    "error",
                    "off_domain",
                    f"{entry.card.name} is outside the legend's domains "
                    f"({', '.join(sorted(identity))})",
                    entry.card,
                    domains=sorted(identity),
                )
    report.note("bans_unchecked", "Not checked: the banned and restricted cards list")


# Yu-Gi-Oh!: Extra Deck monsters by frame (YGOPRODeck) or classification (YGOJSON).
_EXTRA_FRAMES = {"fusion", "synchro", "xyz", "link"}
_BAN_LIMITS = {"Forbidden": 0, "Limited": 1, "Semi-Limited": 2}


def _yg_frame(card: RuleCard) -> str:
    return (card.attributes.get("frame") or "").lower()


def is_extra_deck(card: RuleCard) -> bool:
    frame = _yg_frame(card).removesuffix("_pendulum")
    if frame:
        return frame in _EXTRA_FRAMES
    return bool(_EXTRA_FRAMES & {c.lower() for c in card.attributes.get("classifications") or []})


def _traditional(fmt: Format) -> bool:
    return fmt.id.endswith("_traditional")


def yugioh_legality(card: RuleCard, fmt: Format) -> str:
    """Banned (Forbidden), restricted (Limited, Semi-Limited), not legal (not released
    in that market), unknown (no ban list data: catalog not synced again)."""
    if fmt.legality is None:
        return "legal"
    banlist = card.attributes.get("banlist")
    if banlist is None:
        return "unknown"
    if not card.attributes.get(f"{fmt.legality}_date"):
        return "not_legal"
    status = banlist.get(fmt.legality)
    if status == "Forbidden" and not _traditional(fmt):
        return "banned"
    return "restricted" if status in _BAN_LIMITS else "legal"


def yugioh_copy_limit(card: RuleCard, fmt: Format) -> int:
    if fmt.legality is None:
        return fmt.copies
    status = (card.attributes.get("banlist") or {}).get(fmt.legality)
    limit = _BAN_LIMITS.get(status or "", fmt.copies)
    # Traditional: forbidden cards are limited.
    return max(limit, 1) if _traditional(fmt) else limit


def _check_yugioh(report: Report, fmt: Format, entries: list[Entry]) -> None:
    by_section = _by_section(entries)
    _unused_sections(report, fmt, by_section)
    _size(report, fmt, "main", _count(by_section["main"]), fmt.size, 60)
    _size(report, fmt, "extra", _count(by_section["extra"]), maximum=15)
    _size(report, fmt, "sideboard", _count(by_section["sideboard"]), maximum=fmt.sideboard_max)
    played = by_section["main"] + by_section["extra"] + by_section["sideboard"]
    for entry in played:
        if _yg_frame(entry.card) in ("token", "skill"):
            report.add("error", "not_playable", f"{entry.card.name} cannot be played", entry.card)
        elif entry.section != "sideboard" and (entry.section == "extra") != is_extra_deck(
            entry.card
        ):
            _wrong_section(report, fmt, entry)

    # Three copies of a card (sideboard included), fewer on the ban list.
    copies, cards = _copies(played)
    unknown = []
    for card_id, count in copies.items():
        card = cards[card_id]
        status = yugioh_legality(card, fmt)
        if status == "unknown":
            unknown.append(card.name)
        if status == "not_legal":
            report.add("error", "not_legal", f"{card.name} is not legal in {fmt.name}", card)
            continue
        if status == "banned":
            report.add("error", "banned", f"{card.name} is banned in {fmt.name}", card)
            continue
        limit = fmt.copies if status == "unknown" else yugioh_copy_limit(card, fmt)
        if count > limit:
            report.add(
                "error",
                "copy_limit",
                f"{card.name}: {count} copies, at most {limit} allowed",
                card,
                count=count,
                limit=limit,
            )
    if unknown:
        report.note(
            "legality_unknown",
            f"Ban list status of {_plural(len(unknown), 'card')} not known (sync the "
            "Yu-Gi-Oh! catalog again; OCG cards without a password have none): "
            + ", ".join(sorted(unknown)[:10])
            + ("…" if len(unknown) > 10 else ""),
            count=len(unknown),
            names=sorted(unknown),
        )
    report.note("special_rules", "Not checked: cards with special deck rules")


# Sorcery: card kinds (`category` Avatar / Site / Spell, `type`), copies by rarity.
_SORCERY_COPIES = {"Ordinary": 4, "Exceptional": 3, "Elite": 2, "Unique": 1}


def sorcery_kind(card: RuleCard) -> str | None:
    """ "Avatar", "Site", or the spell's type (Minion, Magic, Aura, Artifact)."""
    category = card.attributes.get("category")
    if category in ("Avatar", "Site"):
        return category
    return card.attributes.get("type") or category


def _check_sorcery(report: Report, fmt: Format, entries: list[Entry]) -> None:
    by_section = _by_section(entries)
    _unused_sections(report, fmt, by_section)
    _size(report, fmt, "avatar", _count(by_section["avatar"]), 1, 1)
    _size(report, fmt, "atlas", _count(by_section["atlas"]), 30)
    _size(report, fmt, "main", _count(by_section["main"]), fmt.size)
    # The 10-card collection is recommended for tournaments.
    collection = _count(by_section["sideboard"])
    _size(report, fmt, "sideboard", collection, maximum=fmt.sideboard_max, level="warning")
    for entry in entries:
        kind = sorcery_kind(entry.card)
        allowed = {
            "avatar": kind == "Avatar",
            "atlas": kind == "Site",
            "main": kind not in ("Avatar", "Site"),
            "sideboard": kind != "Avatar",
        }.get(entry.section, True)
        if not allowed:
            _wrong_section(report, fmt, entry)

    copies, cards = _copies(by_section["atlas"] + by_section["main"] + by_section["sideboard"])
    _copy_limits(
        report, copies, cards, lambda c: _SORCERY_COPIES.get(c.attributes.get("rarity") or "")
    )
    unknown = sorted(
        c.name for c in cards.values() if c.attributes.get("rarity") not in _SORCERY_COPIES
    )
    if unknown:
        report.note(
            "rarity_unknown",
            f"Rarity of {_plural(len(unknown), 'card')} not known: copies not checked",
            count=len(unknown),
            names=unknown,
        )
    report.note("bans_unchecked", "Not checked: the banned and restricted cards list")


_CHECKS: dict[Rules, Callable[[Report, Format, list[Entry]], None]] = {
    "riftbound": _check_riftbound,
    "yugioh": _check_yugioh,
    "sorcery": _check_sorcery,
}


def home_section(fmt: Format, attributes: dict[str, Any], section: Section = "main") -> Section:
    """The section a card added to `section` goes to: legends, runes, battlefields,
    Extra Deck monsters, avatars and sites go to theirs. A sideboard keeps any card but
    legends and avatars."""
    card = RuleCard(0, "", attributes)
    home: Section | None = None
    if fmt.rules == "riftbound":
        home = next((s for s, kind in _RB_KINDS.items() if rb_type(card) == kind), None)
    elif fmt.rules == "yugioh" and is_extra_deck(card):
        home = "extra"
    elif fmt.rules == "sorcery":
        home = {"Avatar": "avatar", "Site": "atlas"}.get(sorcery_kind(card) or "")
    if home is None or section not in ("main", "sideboard"):
        return section
    if section == "sideboard" and home not in ("legend", "avatar"):
        return section
    return home
