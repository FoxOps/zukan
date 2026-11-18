"""Format rules of the Decks module (Magic: The Gathering only so far).

Pure functions over the cards' catalog attributes (`games.mtg.provider.parse_card`):
`types`, `subtypes`, `oracle_text` (or `faces`), `color_identity`, `legalities`. Results
never block saving a deck: a draft is shown with its issues. Rules the data cannot settle
are listed as not verified instead of passing silently."""

import re
from dataclasses import dataclass, field
from typing import Any, Literal

Section = Literal["main", "sideboard", "commander"]
SECTIONS: tuple[Section, ...] = ("commander", "main", "sideboard")
Level = Literal["error", "warning", "info"]


@dataclass(frozen=True)
class Format:
    id: str
    name: str
    # Cards in the deck (main deck, with the commanders): exact or minimum size.
    size: int
    exact_size: bool
    sideboard_max: int | None
    copies: int
    commander: bool


FORMATS = {
    "standard": Format("standard", "Standard", 60, False, 15, 4, False),
    "commander": Format("commander", "Commander", 100, True, None, 1, True),
}
GAMES = {"mtg": tuple(FORMATS)}


@dataclass
class RuleCard:
    card_id: int
    name: str
    attributes: dict[str, Any]

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


def _can_lead(card: RuleCard) -> bool:
    return ("Legendary" in card.types and "Creature" in card.types) or (
        "can be your commander" in card.text.lower()
    )


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


def check(format_id: str, entries: list[Entry]) -> Report:
    report = Report()
    fmt = FORMATS.get(format_id)
    if fmt is None:
        report.note("unknown_format", f"No rules known for format '{format_id}'", format=format_id)
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
            f"Commander has no sideboard: {_plural(side_size, 'card')} not counted",
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

    # Legality.
    unknown = []
    for card in cards.values():
        legalities = card.attributes.get("legalities")
        if legalities is None:
            unknown.append(card.name)
            continue
        status = legalities.get(fmt.id, "not_legal")
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

    if fmt.commander:
        _check_commanders(report, commanders, by_section["main"])
    report.note(
        "not_modelled",
        "Not checked: companion deck conditions, cards with other special deck rules",
    )
    return report


def _check_commanders(report: Report, commanders: list[Entry], main: list[Entry]) -> None:
    leaders = [e.card for e in commanders for _ in range(e.quantity)]
    if not leaders:
        report.add("error", "no_commander", "Choose a commander")
        report.note("color_identity_unchecked", "Color identity is checked once a commander is set")
        return
    if len(leaders) > 2:
        report.add("error", "too_many_commanders", f"{len(leaders)} commanders, at most 2 allowed")
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
        if _can_lead(card) or (backgrounds_allowed and "Background" in card.subtypes):
            continue
        report.add(
            "error",
            "invalid_commander",
            f"{card.name} cannot be a commander (not a legendary creature)",
            card,
        )
    identity = set().union(*(c.color_identity for c in leaders))
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
