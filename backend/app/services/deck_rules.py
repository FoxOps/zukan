"""Format rules of the Decks module: Magic: The Gathering, the Pokémon TCG and Disney
Lorcana.

Pure functions over the cards' catalog attributes. Magic (`games.mtg.provider.parse_card`):
`types`, `subtypes`, `oracle_text` (or `faces`), `color_identity`, `legalities`. Pokémon
(`games.pokemon.provider.parse_card`): `category`, `stage`, `energyType`, the colors (its
types), and per printing the rarity and TCGdex's `legal`. Lorcana
(`games.lorcana.provider`): the colors (inks), `legalities` and `max_copies` from
LorcanaJSON. Results never block saving a
deck: a draft is shown with its issues. Rules the data cannot settle are listed as not
verified instead of passing silently."""

import re
from dataclasses import dataclass, field
from typing import Any, Literal

Section = Literal["main", "sideboard", "commander"]
SECTIONS: tuple[Section, ...] = ("commander", "main", "sideboard")
Level = Literal["error", "warning", "info"]


# Who leads a deck with a commander section: "commander" legendary creatures (or "can be
# your commander"), "pauper" any creature (Pauper Commander: printed uncommon, not
# checked), "oathbreaker" a planeswalker with one instant or sorcery as signature spell.
Leader = Literal["commander", "pauper", "oathbreaker"]
Rules = Literal["mtg", "pokemon", "lorcana"]


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
    # `legalities` key ("core", "infinity"). None: every card legal.
    legality: str | None = None


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
    return Format(id, name, 60, True, None, copies, False, rules="pokemon", legality=legality)


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
    return Format(id, name, 60, False, None, 4, False, rules="lorcana", legality=legality)


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
GAMES = {
    "mtg": tuple(FORMATS),
    "pokemon": tuple(POKEMON_FORMATS),
    "pokemon-asia": tuple(POKEMON_FORMATS),
    "pokemon-china": tuple(POKEMON_FORMATS),
    "lorcana": tuple(LORCANA_FORMATS),
}
FORMATS |= POKEMON_FORMATS | LORCANA_FORMATS


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
    by_section: dict[str, list[Entry]] = {s: [] for s in SECTIONS}
    for entry in entries:
        by_section[entry.section].append(entry)
    commanders = by_section["commander"]
    deck_size = sum(e.quantity for e in by_section["main"] + commanders)
    side_size = sum(e.quantity for e in by_section["sideboard"])

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
    if fmt.sideboard_max is not None and side_size > fmt.sideboard_max:
        report.add(
            "error",
            "sideboard_max",
            f"The sideboard has {_plural(side_size, 'card')}, at most {fmt.sideboard_max} allowed",
            count=side_size,
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

    # Copies of each card across sections (sideboard included, as in tournaments).
    copies: dict[int, int] = {}
    cards: dict[int, RuleCard] = {}
    for entry in entries:
        if fmt.commander and entry.section == "sideboard":
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
    for card in cards.values():
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
        elif status == "restricted" and copies[card.card_id] > 1:
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
    report.note(
        "not_modelled",
        "Not checked: companion deck conditions, cards with other special deck rules",
    )
    return report


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
