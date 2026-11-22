"""Decks module (`app.modules`): decklists checked against their format's rules
(`services.deck_rules`), plain-text import (`services.deck_import`), and owned copies
allocated to decks (`services.decks`). Magic: The Gathering, the Pokémon TCG, Disney
Lorcana, Riftbound, Yu-Gi-Oh! (TCG and OCG) and Sorcery: Contested Realm.

Editing a decklist or importing one never changes the collection or its availability:
only allocating does, and allocating never changes owned quantities."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from app.api.catalog import back_image_link, load_names, orientation, show_card, show_printing
from app.api.collection import copy_image
from app.api.deps import SessionDep
from app.api.shopping import ShoppingListDetailOut, shopping_detail
from app.models import (
    Card,
    CollectionItem,
    Deck,
    DeckAllocation,
    DeckCard,
    Printing,
    ShoppingItem,
    ShoppingList,
    User,
)
from app.modules import require_module
from app.services import deck_export, deck_import, deck_rules, deck_value, decks, shopping
from app.services.deck_rules import FORMATS, GAMES, SECTIONS, Leader, Rules, Section

router = APIRouter(prefix="/decks", tags=["decks"])

DecksUser = require_module("decks")

# Every key of `deck_rules.FORMATS` (a Literal so the OpenAPI schema lists them).
FormatId = Literal[tuple(FORMATS)]  # type: ignore[valid-type]
GameId = Literal[tuple(GAMES)]  # type: ignore[valid-type]
MAX_COPIES = 250


class DeckSectionOut(BaseModel):
    id: Section
    # English name ("Main deck", "Extra Deck", "Atlas"), translated by the web.
    name: str


class DeckFormatOut(BaseModel):
    id: str
    name: str
    size: int
    exact_size: bool
    sideboard_max: int | None
    copies: int
    commander: bool
    # Who may lead (`deck_rules.Leader`), None without a commander section.
    leader: Leader | None
    # Rule set of the game.
    rules: Rules
    # Sections of its decks in the order shown, and those `size` counts.
    sections: list[DeckSectionOut]
    counted: list[Section]


class DeckGameOut(BaseModel):
    game_id: str
    formats: list[DeckFormatOut]


class DeckIssueOut(BaseModel):
    level: Literal["error", "warning", "info"]
    # Stable id (translated by the web with `params`) and English text.
    code: str
    message: str
    card_id: int | None = None
    params: dict = Field(default_factory=dict)


class DeckValidationOut(BaseModel):
    valid: bool
    issues: list[DeckIssueOut]
    # Checks that could not be made (no legality data, rules not modelled).
    unverified: list[DeckIssueOut]


class DeckValueOut(BaseModel):
    """What the deck is worth (`deck_value`), in the currency of the user's price source
    for its game."""

    currency: str
    # Copies allocated to the deck at their own price, the other copies at the cheapest
    # printing and finish, and both together.
    allocated: Decimal
    rest: Decimal
    total: Decimal
    # Copies with no price, counted in none of the three.
    unpriced: int


class DeckOut(BaseModel):
    id: int
    game_id: str
    name: str
    format: str
    # Cards of the sections the format's size counts (main deck, commanders...).
    card_count: int
    # Cards per section.
    counts: dict[str, int]
    errors: int
    # Copies the deck asks for (all sections), those the user has for it (allocated to it
    # or free in the collection, not those other decks hold) and those allocated to it.
    copies: int = 0
    owned: int = 0
    allocated: int = 0
    value: DeckValueOut | None = None
    created_at: datetime
    updated_at: datetime


class DeckIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    game_id: GameId = "mtg"
    format: FormatId

    @model_validator(mode="after")
    def _format_of_game(self) -> "DeckIn":
        if self.format not in GAMES[self.game_id]:
            raise ValueError(f"Format '{self.format}' is not a format of {self.game_id}")
        return self


class DeckUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    format: FormatId | None = None


class DeckLineOut(BaseModel):
    """Copies of the card asked for in one section, of one printing or any."""

    section: Section
    # None: any printing.
    printing_id: int | None
    set_code: str | None = None
    set_name: str | None = None
    collector_number: str | None = None
    quantity: int
    # The printing's picture (its allocated copy's, else the catalog's); any printing:
    # the card's (`DeckEntryOut.image`).
    image: str | None = None
    # Back face of a double-faced printing.
    back_image: str | None = None
    # Copies allocated to this line: copies of its printing first, then lines of any
    # printing take the rest.
    allocated: int
    # Owned copies of the printing no deck holds (None: any printing, see the card).
    available: int | None = None


class DeckEntryOut(BaseModel):
    card_id: int
    name: str
    translation: str | None = None
    # The allocated copy's picture (the one most copies come from), else the card's.
    image: str | None
    # Back face of that picture's printing (double-faced cards).
    back_image: str | None = None
    # "landscape": Riftbound battlefields, Lorcana locations.
    orientation: str = "portrait"
    colors: list[str]
    mana_cost: str | None
    type_line: str | None
    # Card type group shown in the list (Creature, Land... / Pokémon, Supporter...).
    group: str
    # Copies asked for per section (every printing).
    quantities: dict[str, int]
    # The same copies line by line (printing asked for, or any), sections in order.
    lines: list[DeckLineOut]
    # All sections together; owned; allocated to this deck; free in the collection
    # (owned by the user, no deck holds them); allocated to the user's other decks.
    requested: int
    owned: int
    allocated: int
    available: int
    allocated_elsewhere: int
    # Collection items with free copies (several: the user picks which to allocate).
    free_items: int
    missing: int
    status: Literal["missing", "owned", "allocated"]
    legal: Literal["legal", "banned", "not_legal", "restricted", "unknown"]


class DeckDetailOut(BaseModel):
    deck: DeckOut
    # Card type groups of the game, in the order shown.
    groups: list[str]
    entries: list[DeckEntryOut]
    validation: DeckValidationOut


class DeckCardIn(BaseModel):
    card_id: int
    # None: the card's section in the main deck (`deck_rules.home_section`: a rune goes
    # to the rune deck, a site to the atlas...).
    section: Section | None = None
    # The printing asked for, None: any.
    printing_id: int | None = None
    # 0 removes the line.
    quantity: int = Field(ge=0, le=MAX_COPIES)
    # Add `quantity` copies to the line (adding from the catalog search).
    add: bool = False


class DeckLineMoveIn(BaseModel):
    """Move copies of a line to another printing (or any), merged with that line when
    the deck has it."""

    card_id: int
    section: Section = "main"
    printing_id: int | None = None
    to_printing_id: int | None = None
    # Copies moved, None: the whole line.
    quantity: int | None = Field(default=None, ge=1, le=MAX_COPIES)


class DeckPrintingOut(BaseModel):
    """A printing of the card, to pick the one a deck line asks for."""

    id: int
    set_code: str
    set_name: str
    collector_number: str | None
    release_date: date | None
    image: str | None
    # The user's copies of the printing, and those no deck holds.
    owned: int
    available: int


class DeckAllocationIn(BaseModel):
    card_id: int
    quantity: int = Field(default=1, ge=1, le=MAX_COPIES)
    # One collection item; None: the items with the most free copies.
    item_id: int | None = None


class DeckItemOut(BaseModel):
    """A collection item of the card, for picking the copies to allocate."""

    id: int
    printing_id: int
    image: str | None
    set_code: str
    set_name: str
    collector_number: str | None
    finish: str
    condition: str
    language: str
    quantity: int
    allocated: int
    allocated_elsewhere: int
    free: int


class DeckImportPreviewIn(BaseModel):
    text: str = Field(max_length=50_000)
    game_id: GameId = "mtg"


class DeckCandidateOut(BaseModel):
    card_id: int
    name: str
    type_line: str | None


class DeckImportPrintingOut(BaseModel):
    id: int
    set_code: str
    collector_number: str | None


class DeckImportLineOut(BaseModel):
    line: int
    text: str
    quantity: int
    name: str
    section: Section
    # Set code and collector number the line names ("(M10) 146", "PAF 7").
    set_code: str | None = None
    collector_number: str | None = None
    # The printing they name, among the resolved card's (None: any printing).
    printing: DeckImportPrintingOut | None = None
    status: Literal["resolved", "ambiguous", "unknown"]
    # The card (resolved), the cards it could be (ambiguous), close names (unknown).
    card: DeckCandidateOut | None = None
    candidates: list[DeckCandidateOut] = []


class DeckImportPreviewOut(BaseModel):
    lines: list[DeckImportLineOut]
    # Lines that are neither cards nor section headers.
    skipped: list[str]


class DeckImportEntryIn(BaseModel):
    card_id: int
    section: Section = "main"
    printing_id: int | None = None
    quantity: int = Field(ge=1, le=MAX_COPIES)


class DeckImportIn(BaseModel):
    entries: list[DeckImportEntryIn] = Field(max_length=600)
    # Replace the decklist (allocations of cards that leave it are released), or add.
    replace: bool = False


# Order of card type groups in the list; Magic: the first type a card has wins.
GROUPS = (
    "Creature",
    "Planeswalker",
    "Battle",
    "Instant",
    "Sorcery",
    "Artifact",
    "Enchantment",
    "Land",
)


POKEMON_GROUPS = ("Pokémon", "Supporter", "Item", "Pokémon Tool", "Stadium", "Trainer", "Energy")
# TCGdex trainer types; Technical Machines are Pokémon Tools.
_TRAINER_GROUPS = {
    "Supporter": "Supporter",
    "Item": "Item",
    "Tool": "Pokémon Tool",
    "Technical Machine": "Pokémon Tool",
    "Stadium": "Stadium",
}


# Lorcana card types; songs are actions.
LORCANA_GROUPS = ("Character", "Action", "Song", "Item", "Location")
RIFTBOUND_GROUPS = ("Legend", "Unit", "Spell", "Gear", "Rune", "Battlefield")
# Main Deck cards, then Extra Deck monsters by summoning kind.
YUGIOH_GROUPS = ("Monster", "Spell", "Trap", "Fusion", "Synchro", "Xyz", "Link")
SORCERY_GROUPS = ("Avatar", "Site", "Minion", "Magic", "Aura", "Artifact")
_GAME_GROUPS = {
    "mtg": GROUPS,
    "lorcana": LORCANA_GROUPS,
    "riftbound": RIFTBOUND_GROUPS,
    "yugioh": YUGIOH_GROUPS,
    "yugioh-ocg": YUGIOH_GROUPS,
    "sorcery": SORCERY_GROUPS,
}


def _groups(game_id: str) -> tuple[str, ...]:
    return (*_GAME_GROUPS.get(game_id, POKEMON_GROUPS), "Other")


def _yugioh_group(card: Card) -> str:
    """Spell, Trap, the Extra Deck kind (Fusion, Synchro, Xyz, Link) or Monster."""
    frame = (card.attributes.get("frame") or "").lower().removesuffix("_pendulum")
    if frame in ("token", "skill"):
        return "Other"
    kinds = (
        [frame]
        if frame
        else [
            (card.attributes.get("card_type") or "").lower(),
            *(c.lower() for c in card.attributes.get("classifications") or []),
        ]
    )
    for group in ("Spell", "Trap", "Fusion", "Synchro", "Xyz", "Link"):
        if group.lower() in kinds:
            return group
    return "Monster" if frame or "monster" in kinds else "Other"


def _front_types(card: Card) -> list[str]:
    """Magic card types of the front face: an "Instant // Land" card is an instant."""
    faces = card.attributes.get("faces") or []
    line = (faces[0].get("type_line") if faces else None) or card.attributes.get("type_line")
    if not line:
        return card.attributes.get("types") or []
    return line.split(" // ")[0].split("—")[0].split()


def _group(card: Card) -> str:
    if card.game_id == "lorcana":
        kind = card.attributes.get("type")
        if kind == "Action" and "Song" in (card.attributes.get("classifications") or []):
            return "Song"
        return kind if kind in LORCANA_GROUPS else "Other"
    if card.game_id == "riftbound":
        kind = card.attributes.get("type")
        return kind if kind in RIFTBOUND_GROUPS else "Other"
    if card.game_id.startswith("yugioh"):
        return _yugioh_group(card)
    if card.game_id == "sorcery":
        kind = deck_rules.sorcery_kind(_rule_card(card))
        return kind if kind in SORCERY_GROUPS else "Other"
    if card.game_id != "mtg":
        category = card.attributes.get("category")
        if category in ("Pokemon", "Pokémon"):
            return "Pokémon"
        if category == "Trainer":
            return _TRAINER_GROUPS.get(card.attributes.get("trainerType") or "", "Trainer")
        return "Energy" if category == "Energy" else "Other"
    types = _front_types(card)
    # Artifact creatures are creatures, artifact lands are lands.
    if "Land" in types and "Creature" not in types:
        return "Land"
    return next((g for g in GROUPS if g in types), "Other")


def _rule_card(card: Card) -> deck_rules.RuleCard:
    return deck_rules.RuleCard(card.id, card.name, card.attributes, card.colors)


def _joined(*parts: object) -> str | None:
    return " — ".join(str(p) for p in parts if p not in (None, "")) or None


def _type_line(card: Card) -> str | None:
    """Magic's type line; the other games: kind, subtypes and cost."""
    a = card.attributes
    if card.game_id == "lorcana" and (kind := a.get("type")):
        cost = a.get("cost")
        return _joined(
            kind,
            ", ".join(a.get("classifications") or []),
            f"{cost} ink" if cost is not None else None,
        )
    if card.game_id == "riftbound" and (kind := a.get("type")):
        energy = a.get("energy")
        return _joined(
            " ".join(p for p in (a.get("supertype"), kind) if p),
            ", ".join(d.capitalize() for d in a.get("domains") or []),
            f"{energy} energy" if energy is not None else None,
        )
    if card.game_id.startswith("yugioh"):
        level = a.get("level")
        return _joined(
            a.get("type") or (a.get("card_type") or "").capitalize(),
            a.get("race"),
            f"Link {a['link']}" if a.get("link") else (f"Level {level}" if level else None),
        )
    if card.game_id == "sorcery" and (kind := a.get("type")):
        cost = a.get("cost")
        return _joined(
            kind,
            ", ".join(a.get("subtypes") or []),
            a.get("rarity"),
            f"{cost} mana" if cost is not None else None,
        )
    return a.get("type_line")


def _candidate(card: Card) -> DeckCandidateOut:
    return DeckCandidateOut(card_id=card.id, name=card.name, type_line=_type_line(card))


async def _rule_printings(
    session: SessionDep, decks_: list[Deck]
) -> dict[int, list[deck_rules.RulePrinting]]:
    """Rarity and legality of the printings of Pokémon decks' cards (Magic needs none)."""
    card_ids = {e.card_id for d in decks_ if d.game_id != "mtg" for e in d.cards}
    found: dict[int, list[deck_rules.RulePrinting]] = {}
    if card_ids:
        rows = await session.execute(
            select(Printing.card_id, Printing.rarity, Printing.attributes["legal"]).where(
                Printing.card_id.in_(card_ids)
            )
        )
        for card_id, rarity, legal in rows:
            found.setdefault(card_id, []).append(deck_rules.RulePrinting(rarity, legal))
    return found


def _rule_entries(
    deck: Deck, printings: dict[int, list[deck_rules.RulePrinting]]
) -> list[deck_rules.Entry]:
    """One entry per card and section: lines of several printings added up."""
    entries: dict[tuple[int, str], deck_rules.Entry] = {}
    for e in deck.cards:
        entry = entries.get((e.card_id, e.section))
        if entry is not None:
            entry.quantity += e.quantity
            continue
        entries[e.card_id, e.section] = deck_rules.Entry(
            deck_rules.RuleCard(
                e.card_id,
                e.card.name,
                e.card.attributes,
                e.card.colors,
                printings.get(e.card_id, []),
            ),
            e.section,
            e.quantity,
        )
    return list(entries.values())


async def _check(
    session: SessionDep, deck: Deck
) -> tuple[deck_rules.Report, list[deck_rules.Entry]]:
    entries = _rule_entries(deck, await _rule_printings(session, [deck]))
    return deck_rules.check(deck.format, entries), entries


def _item_image(printing: Printing, language: str, ui_lang: str) -> str | None:
    """Picture of a collection copy (set loaded), as the collection shows it."""
    _, picked = show_printing(printing, {}, {}, ui_lang)
    return copy_image(printing, language, picked)


async def _allocated_images(
    session: SessionDep, deck: Deck, ui_lang: str
) -> tuple[dict[int, tuple[str, Printing]], dict[int, str]]:
    """Per card (with its printing, for the back face), and per printing, the picture of
    the copy most of its allocated copies come from."""
    allocations = await session.scalars(
        select(DeckAllocation)
        .where(DeckAllocation.deck_id == deck.id, DeckAllocation.quantity > 0)
        .order_by(DeckAllocation.quantity.desc(), DeckAllocation.id)
        .options(
            selectinload(DeckAllocation.item)
            .selectinload(CollectionItem.printing)
            .selectinload(Printing.set)
        )
    )
    shown: dict[int, tuple[str, Printing]] = {}
    by_printing: dict[int, str] = {}
    for allocation in allocations:
        item = allocation.item
        card_id = item.printing.card_id
        if item.printing_id in by_printing:
            continue
        if image := _item_image(item.printing, item.language, ui_lang):
            by_printing[item.printing_id] = image
            shown.setdefault(card_id, (image, item.printing))
    return shown, by_printing


SECTION_ORDER = SECTIONS


def _sorted_lines(lines: list[DeckCard]) -> list[DeckCard]:
    """Sections in order; in a section, printings by set code and number, any last."""
    return sorted(
        lines,
        key=lambda e: (
            SECTION_ORDER.index(e.section),
            e.printing is None,
            e.printing.set.code if e.printing else "",
            _number_key(e.printing.collector_number if e.printing else None),
        ),
    )


def _number_key(number: str | None) -> tuple[int, str]:
    digits = "".join(c for c in number or "" if c.isdigit())
    return (int(digits) if digits else 0, number or "")


def _deck_out(
    deck: Deck,
    report: deck_rules.Report,
    stock: dict[int, decks.CardStock],
    value: deck_value.DeckValue | None = None,
) -> DeckOut:
    counts: dict[str, int] = {}
    for e in deck.cards:
        counts[e.section] = counts.get(e.section, 0) + e.quantity
    fmt = FORMATS.get(deck.format)
    counted = fmt.counted if fmt else ("commander", "main")
    return DeckOut(
        id=deck.id,
        game_id=deck.game_id,
        name=deck.name,
        format=deck.format,
        card_count=sum(n for section, n in counts.items() if section in counted),
        counts={s: counts[s] for s in SECTION_ORDER if s in counts},
        errors=sum(1 for i in report.issues if i.level == "error"),
        copies=sum(c.requested for c in stock.values()),
        owned=sum(c.covered for c in stock.values()),
        allocated=sum(min(c.allocated, c.requested) for c in stock.values()),
        value=DeckValueOut(
            currency=value.currency,
            allocated=value.allocated,
            rest=value.rest,
            total=value.total,
            unpriced=value.unpriced,
        )
        if value
        else None,
        created_at=deck.created_at,
        updated_at=deck.updated_at,
    )


def _issue_out(issue: deck_rules.Issue) -> DeckIssueOut:
    return DeckIssueOut(
        level=issue.level,
        code=issue.code,
        message=issue.message,
        card_id=issue.card_id,
        params=issue.params,
    )


async def _own(session: SessionDep, user: User, deck_id: int, lock: bool = False) -> Deck:
    query = (
        select(Deck)
        .where(Deck.id == deck_id, Deck.user_id == user.id)
        .options(
            selectinload(Deck.cards).selectinload(DeckCard.card),
            selectinload(Deck.cards).selectinload(DeckCard.printing).selectinload(Printing.set),
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        # Serializes edits of one deck (quantity checks against allocations).
        query = query.with_for_update(of=Deck)
    found = await session.scalar(query)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deck not found")
    return found


async def _detail(session: SessionDep, user: User, deck_id: int) -> DeckDetailOut:
    deck = await _own(session, user, deck_id)
    report, rule_entries = await _check(session, deck)
    rule_cards = {e.card.card_id: e.card for e in rule_entries}
    fmt = FORMATS.get(deck.format)
    card_ids = {e.card_id for e in deck.cards}
    cards = {
        c.id: c
        for c in await session.scalars(
            select(Card)
            .where(Card.id.in_(card_ids))
            .options(selectinload(Card.printings).selectinload(Printing.set))
        )
    }
    stock = await decks.stock(session, deck, card_ids)
    card_names, printing_names = await load_names(session, card_ids)
    allocated_images, printing_images = await _allocated_images(session, deck, user.language)
    entries = []
    for card_id in card_ids:
        card = cards[card_id]
        shown = show_card(card, card_names, printing_names, user.language)
        # The allocated copy's picture, else the card's; its back for double-faced cards.
        front, front_printing = allocated_images.get(card_id, (shown.image, shown.printing))
        counts = stock[card_id]
        quantities: dict[str, int] = {}
        card_lines = _sorted_lines([e for e in deck.cards if e.card_id == card_id])
        for e in card_lines:
            quantities[e.section] = quantities.get(e.section, 0) + e.quantity
        allocated = decks.line_allocations(
            [(e.printing_id, e.quantity) for e in card_lines], counts.allocated_by_printing
        )
        lines = []
        for e, line_allocated in zip(card_lines, allocated, strict=True):
            line = DeckLineOut(
                section=e.section,
                printing_id=e.printing_id,
                quantity=e.quantity,
                allocated=line_allocated,
            )
            if e.printing is not None:
                line.set_code = e.printing.set.code
                line.set_name = e.printing.set.name
                line.collector_number = e.printing.collector_number
                line.image = (
                    printing_images.get(e.printing_id)
                    or (show_printing(e.printing, card_names, printing_names, user.language)[1])
                )
                line.back_image = back_image_link(e.printing)
                line.available = counts.available_by_printing.get(e.printing_id, 0)
            lines.append(line)
        entries.append(
            DeckEntryOut(
                card_id=card_id,
                name=shown.name.name,
                translation=shown.name.translation,
                image=front,
                back_image=back_image_link(front_printing) if front_printing else None,
                orientation=orientation(shown.printing) if shown.printing else "portrait",
                colors=card.colors,
                mana_cost=card.attributes.get("mana_cost")
                or " // ".join(
                    f["mana_cost"] for f in card.attributes.get("faces", []) if f.get("mana_cost")
                )
                or None,
                type_line=_type_line(card),
                group=_group(card),
                quantities=quantities,
                lines=lines,
                requested=counts.requested,
                owned=counts.owned,
                allocated=counts.allocated,
                available=counts.available,
                allocated_elsewhere=counts.allocated_all - counts.allocated,
                free_items=counts.free_items,
                missing=counts.missing,
                status=counts.status,
                legal=deck_rules.legality(rule_cards[card_id], fmt) if fmt else "unknown",
            )
        )
    order = _groups(deck.game_id)
    entries.sort(key=lambda e: (order.index(e.group), e.name.casefold()))
    values = await deck_value.deck_values(session, user.price_source, [deck], {deck.id: stock})
    return DeckDetailOut(
        deck=_deck_out(deck, report, stock, values[deck.id]),
        groups=list(order),
        entries=entries,
        validation=DeckValidationOut(
            valid=report.valid,
            issues=[_issue_out(i) for i in report.issues],
            unverified=[_issue_out(i) for i in report.unverified],
        ),
    )


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


def _format_out(fmt: deck_rules.Format) -> DeckFormatOut:
    return DeckFormatOut(
        **{k: v for k, v in fmt.__dict__.items() if k not in ("sections", "counted")},
        sections=[DeckSectionOut(id=s, name=name) for s, name in fmt.sections],
        counted=list(fmt.counted),
    )


@router.get("/formats")
async def list_formats(_: DecksUser) -> list[DeckGameOut]:
    """Games and formats decks can be built for."""
    return [
        DeckGameOut(
            game_id=game_id,
            formats=[_format_out(FORMATS[f]) for f in formats],
        )
        for game_id, formats in GAMES.items()
    ]


@router.get("")
async def list_decks(user: DecksUser, session: SessionDep) -> list[DeckOut]:
    """The user's decks, last changed first."""
    found = await session.scalars(
        select(Deck)
        .where(Deck.user_id == user.id)
        .order_by(Deck.updated_at.desc(), Deck.id.desc())
        .options(selectinload(Deck.cards).selectinload(DeckCard.card))
    )
    found = list(found)
    printings = await _rule_printings(session, found)
    stocks = await decks.stocks(session, user.id, found)
    values = await deck_value.deck_values(session, user.price_source, found, stocks)
    return [
        _deck_out(
            d, deck_rules.check(d.format, _rule_entries(d, printings)), stocks[d.id], values[d.id]
        )
        for d in found
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_deck(body: DeckIn, user: DecksUser, session: SessionDep) -> DeckDetailOut:
    deck = Deck(user_id=user.id, game_id=body.game_id, name=body.name.strip(), format=body.format)
    session.add(deck)
    await session.commit()
    return await _detail(session, user, deck.id)


@router.get("/{deck_id}")
async def get_deck(deck_id: int, user: DecksUser, session: SessionDep) -> DeckDetailOut:
    """Cards by type with their copies (asked for, owned, allocated, available), and the
    format check."""
    return await _detail(session, user, deck_id)


@router.patch("/{deck_id}")
async def update_deck(
    deck_id: int, body: DeckUpdateIn, user: DecksUser, session: SessionDep
) -> DeckDetailOut:
    """Rename or change the format (cards and allocations kept)."""
    deck = await _own(session, user, deck_id, lock=True)
    if body.name is not None:
        deck.name = body.name.strip()
    if body.format is not None:
        if body.format not in GAMES.get(deck.game_id, ()):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Not a format of the deck's game"
            )
        deck.format = body.format
    await session.commit()
    return await _detail(session, user, deck_id)


@router.delete("/{deck_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deck(deck_id: int, user: DecksUser, session: SessionDep) -> None:
    """Delete the deck; its allocated copies become available again (the collection
    keeps them)."""
    await session.delete(await _own(session, user, deck_id, lock=True))
    await session.commit()


async def _card(session: SessionDep, deck: Deck, card_id: int) -> Card:
    card = await session.get(Card, card_id)
    if card is None or card.game_id != deck.game_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found")
    return card


@router.put("/{deck_id}/cards")
async def set_card(
    deck_id: int, body: DeckCardIn, user: DecksUser, session: SessionDep
) -> DeckDetailOut:
    """Set the copies of a card in a section, of one printing or any (0 removes the
    line). Copies allocated beyond the deck's new total are released; the collection is
    not changed."""
    deck = await _own(session, user, deck_id, lock=True)
    card = await _card(session, deck, body.card_id)
    await _check_printing(session, body.card_id, body.printing_id)
    section = body.section
    if section is None:
        fmt = FORMATS.get(deck.format)
        section = deck_rules.home_section(fmt, card.attributes) if fmt else "main"
    quantity = body.quantity
    if body.add and (line := _line(deck, body.card_id, section, body.printing_id)):
        quantity = min(MAX_COPIES, line.quantity + quantity)
    await decks.set_line(session, deck, body.card_id, section, body.printing_id, quantity)
    await decks.release_excess(session, deck, [body.card_id])
    deck.updated_at = func.now()
    await session.commit()
    return await _detail(session, user, deck_id)


@router.post("/{deck_id}/cards/move")
async def move_line(
    deck_id: int, body: DeckLineMoveIn, user: DecksUser, session: SessionDep
) -> DeckDetailOut:
    """Ask for another printing (or any) for copies of a line: the whole line, or some
    copies split off into their own line. Allocations are kept."""
    deck = await _own(session, user, deck_id, lock=True)
    await _check_printing(session, body.card_id, body.to_printing_id)
    line = _line(deck, body.card_id, body.section, body.printing_id)
    if line is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deck line not found")
    moved = min(body.quantity or line.quantity, line.quantity)
    if body.to_printing_id != body.printing_id:
        target = _line(deck, body.card_id, body.section, body.to_printing_id)
        current = target.quantity if target else 0
        await decks.set_line(
            session, deck, body.card_id, body.section, body.printing_id, line.quantity - moved
        )
        await decks.set_line(
            session,
            deck,
            body.card_id,
            body.section,
            body.to_printing_id,
            min(MAX_COPIES, current + moved),
        )
        await decks.release_excess(session, deck, [body.card_id])
        deck.updated_at = func.now()
        await session.commit()
    return await _detail(session, user, deck_id)


def _line(deck: Deck, card_id: int, section: str, printing_id: int | None) -> DeckCard | None:
    return next(
        (
            e
            for e in deck.cards
            if e.card_id == card_id and e.section == section and e.printing_id == printing_id
        ),
        None,
    )


async def _check_printing(session: SessionDep, card_id: int, printing_id: int | None) -> None:
    if printing_id is None:
        return
    found = await session.scalar(
        select(Printing.id).where(Printing.id == printing_id, Printing.card_id == card_id)
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Printing not found for this card")


@router.post("/{deck_id}/allocate")
async def allocate(
    deck_id: int, body: DeckAllocationIn, user: DecksUser, session: SessionDep
) -> DeckDetailOut:
    """Set owned copies aside for this deck (no more than the deck asks for, nor than
    the copies no deck holds). Owned quantities do not change."""
    deck = await _own(session, user, deck_id, lock=True)
    try:
        await decks.allocate(session, deck, body.card_id, body.quantity, body.item_id)
    except decks.AllocationError as exc:
        await session.rollback()
        raise _conflict(exc) from exc
    await session.commit()
    return await _detail(session, user, deck_id)


@router.post("/{deck_id}/release")
async def release(
    deck_id: int, body: DeckAllocationIn, user: DecksUser, session: SessionDep
) -> DeckDetailOut:
    """Give allocated copies back to the collection's available copies."""
    deck = await _own(session, user, deck_id, lock=True)
    try:
        await decks.release(session, deck, body.card_id, body.quantity, body.item_id)
    except decks.AllocationError as exc:
        await session.rollback()
        raise _conflict(exc) from exc
    await session.commit()
    return await _detail(session, user, deck_id)


@router.get("/{deck_id}/cards/{card_id}/items")
async def card_items(
    deck_id: int, card_id: int, user: DecksUser, session: SessionDep
) -> list[DeckItemOut]:
    """The user's copies of a card (every printing), with what decks hold of them."""
    deck = await _own(session, user, deck_id)
    held = await decks.items(session, deck, card_id)
    printings = {
        p.id: p
        for p in await session.scalars(
            select(Printing)
            .where(Printing.id.in_({s.item.printing_id for s in held}))
            .options(selectinload(Printing.set))
        )
    }
    return [
        DeckItemOut(
            id=s.item.id,
            printing_id=s.item.printing_id,
            image=_item_image(printings[s.item.printing_id], s.item.language, user.language),
            set_code=printings[s.item.printing_id].set.code,
            set_name=printings[s.item.printing_id].set.name,
            collector_number=printings[s.item.printing_id].collector_number,
            finish=s.item.finish,
            condition=s.item.condition,
            language=s.item.language,
            quantity=s.item.quantity,
            allocated=s.allocated,
            allocated_elsewhere=s.allocated_all - s.allocated,
            free=max(0, s.free),
        )
        for s in held
        if s.item.quantity > 0 or s.allocated_all > 0
    ]


@router.get("/{deck_id}/cards/{card_id}/printings")
async def card_printings(
    deck_id: int, card_id: int, user: DecksUser, session: SessionDep
) -> list[DeckPrintingOut]:
    """The card's printings (owned ones, then newest sets first), with the user's copies
    of each."""
    deck = await _own(session, user, deck_id)
    await _card(session, deck, card_id)
    printings = list(
        await session.scalars(
            select(Printing).where(Printing.card_id == card_id).options(selectinload(Printing.set))
        )
    )
    held = await decks.items(session, deck, card_id)
    owned: dict[int, int] = {}
    free: dict[int, int] = {}
    for s in held:
        owned[s.item.printing_id] = owned.get(s.item.printing_id, 0) + s.item.quantity
        free[s.item.printing_id] = free.get(s.item.printing_id, 0) + max(0, s.free)
    card_names, printing_names = await load_names(session, {card_id})
    printings.sort(
        key=lambda p: (
            p.id not in owned,
            -(p.set.release_date or date.min).toordinal(),
            p.set.code,
            _number_key(p.collector_number),
        )
    )
    return [
        DeckPrintingOut(
            id=p.id,
            set_code=p.set.code,
            set_name=p.set.name,
            collector_number=p.collector_number,
            release_date=p.set.release_date,
            image=show_printing(p, card_names, printing_names, user.language)[1],
            owned=owned.get(p.id, 0),
            available=free.get(p.id, 0),
        )
        for p in printings
    ]


class DeckExportOut(BaseModel):
    text: str
    # Suggested file name ("Burn.txt").
    filename: str


@router.get("/{deck_id}/export")
async def export_deck(
    deck_id: int, user: DecksUser, session: SessionDep, sets: bool = True
) -> DeckExportOut:
    """The decklist as text in the game's usual format (`services.deck_export`), read
    back by the import. With `sets`: each line's printing (set code and number); lines of
    any printing take their allocated copies' printings, Pokémon ones the newest printing
    for the copies not allocated (Pokémon TCG Live needs one)."""
    deck = await _own(session, user, deck_id)
    card_ids = {e.card_id for e in deck.cards}
    cards = {
        c.id: c
        for c in await session.scalars(
            select(Card)
            .where(Card.id.in_(card_ids))
            .options(selectinload(Card.printings).selectinload(Printing.set))
        )
    }
    printings = {p.id: p for c in cards.values() for p in c.printings}
    stock = await decks.stock(session, deck, card_ids)
    pokemon = deck.game_id.startswith("pokemon")
    order = _groups(deck.game_id)
    lines = []
    for card_id in sorted(
        card_ids, key=lambda c: (order.index(_group(cards[c])), cards[c].name.casefold())
    ):
        card = cards[card_id]
        card_lines = _sorted_lines([e for e in deck.cards if e.card_id == card_id])
        parts = decks.line_printings(
            [(e.printing_id, e.quantity) for e in card_lines],
            stock[card_id].allocated_by_printing,
        )
        newest = max(
            card.printings,
            key=lambda p: (p.set.release_date or date.min, p.id),
            default=None,
        )
        for e, line_parts in zip(card_lines, parts, strict=True):
            merged: dict[int | None, int] = {}
            for printing_id, quantity in line_parts:
                if printing_id is None and pokemon and newest is not None:
                    printing_id = newest.id
                merged[printing_id] = merged.get(printing_id, 0) + quantity
            for printing_id, quantity in merged.items():
                printing = printings.get(printing_id) if printing_id is not None else None
                lines.append(
                    deck_export.ExportLine(
                        name=card.name,
                        section=e.section,
                        group=_group(card),
                        quantity=quantity,
                        set_code=printing.set.code if printing else None,
                        collector_number=printing.collector_number if printing else None,
                    )
                )
    if not sets:
        # One line per card and section.
        joined: dict[tuple[str, str], deck_export.ExportLine] = {}
        for line in lines:
            if (found := joined.get((line.name, line.section))) is not None:
                found.quantity += line.quantity
            else:
                joined[line.name, line.section] = line
        lines = list(joined.values())
    return DeckExportOut(
        text=deck_export.export_text(deck.game_id, lines, sets),
        filename=_filename(deck.name, "txt"),
    )


def _filename(name: str, extension: str) -> str:
    """A file name from a deck's name ("Burn.txt")."""
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()
    return f"{safe or 'deck'}.{extension}"


class ShoppingLineOut(BaseModel):
    card_id: int | None
    printing_id: int | None
    name: str
    translation: str | None
    set_code: str | None
    collector_number: str | None
    quantity: int


class ShoppingOut(BaseModel):
    # Cards to get, in the decklist's order; empty when the deck has every copy.
    lines: list[ShoppingLineOut]


async def _shopping_lines(
    session: SessionDep, user: User, deck: Deck
) -> list[shopping.ShoppingLine]:
    """Copies the deck misses (`decks.line_missing`), by card in the decklist's order:
    one line per printing asked for, or for any printing."""
    card_ids = {e.card_id for e in deck.cards}
    cards = {
        c.id: c
        for c in await session.scalars(
            select(Card)
            .where(Card.id.in_(card_ids))
            .options(selectinload(Card.printings).selectinload(Printing.set))
        )
    }
    stock = await decks.stock(session, deck, card_ids)
    card_names, printing_names = await load_names(session, card_ids)
    order = _groups(deck.game_id)
    result = []
    for card_id in sorted(
        card_ids, key=lambda c: (order.index(_group(cards[c])), cards[c].name.casefold())
    ):
        counts = stock[card_id]
        if not counts.missing:
            continue
        card = cards[card_id]
        card_lines = _sorted_lines([e for e in deck.cards if e.card_id == card_id])
        wanted = [(e.printing_id, e.quantity) for e in card_lines]
        missing = decks.line_missing(
            wanted,
            decks.line_allocations(wanted, counts.allocated_by_printing),
            counts.available_by_printing,
            counts.missing,
        )
        translation = show_card(card, card_names, printing_names, user.language).name.name
        merged: dict[int | None, shopping.ShoppingLine] = {}
        for e, quantity in zip(card_lines, missing, strict=True):
            if quantity <= 0:
                continue
            if (found := merged.get(e.printing_id)) is not None:
                found.quantity += quantity
                continue
            merged[e.printing_id] = shopping.ShoppingLine(
                card_id=card_id,
                printing_id=e.printing_id,
                name=card.name,
                translation=translation if translation != card.name else None,
                set_code=e.printing.set.code.upper() if e.printing else None,
                collector_number=e.printing.collector_number if e.printing else None,
                quantity=quantity,
            )
        result.extend(merged.values())
    return result


@router.get("/{deck_id}/shopping")
async def deck_shopping(deck_id: int, user: DecksUser, session: SessionDep) -> ShoppingOut:
    """The cards the deck misses: copies neither allocated to it nor free in the
    collection (copies other decks hold count as missing)."""
    deck = await _own(session, user, deck_id)
    lines = await _shopping_lines(session, user, deck)
    return ShoppingOut(
        lines=[
            ShoppingLineOut(**{k: v for k, v in line.__dict__.items() if k != "bought"})
            for line in lines
        ]
    )


SHOPPING_TYPES = {
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
    "pdf": "application/pdf",
}


@router.get(
    "/{deck_id}/shopping/download",
    response_class=Response,
    responses={200: {"content": {t: {} for t in SHOPPING_TYPES.values()}}},
)
async def download_shopping(
    deck_id: int,
    user: DecksUser,
    session: SessionDep,
    format: Literal["txt", "md", "pdf"] = "txt",
) -> Response:
    """The cards the deck misses as a check list file, in the user's language."""
    deck = await _own(session, user, deck_id)
    lines = await _shopping_lines(session, user, deck)
    render = {"txt": shopping.to_txt, "md": shopping.to_md, "pdf": shopping.to_pdf}[format]
    content = render(deck.name, lines, user.language, date.today())
    return Response(
        content,
        media_type=SHOPPING_TYPES[format],
        headers={
            "Content-Disposition": f'attachment; filename="{_filename(deck.name, format)}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/{deck_id}/shopping-list", status_code=status.HTTP_201_CREATED)
async def send_shopping_list(
    deck_id: int, user: DecksUser, session: SessionDep
) -> ShoppingListDetailOut:
    """Saves the cards the deck misses as a shopping list for the Android app: a copy,
    later deck changes do not change it."""
    deck = await _own(session, user, deck_id)
    lines = await _shopping_lines(session, user, deck)
    if not lines:
        raise HTTPException(status.HTTP_409_CONFLICT, "The deck misses no card")
    found = ShoppingList(user_id=user.id, deck_id=deck.id, game_id=deck.game_id, name=deck.name)
    found.items = [ShoppingItem(position=i, **line.__dict__) for i, line in enumerate(lines)]
    session.add(found)
    await session.commit()
    return await shopping_detail(session, user, found.id)


@router.post("/import/preview")
async def import_preview(
    body: DeckImportPreviewIn, _: DecksUser, session: SessionDep
) -> DeckImportPreviewOut:
    """Read a plain-text decklist ("4 Lightning Bolt", "Commander" / "Sideboard"
    headers): the card each line names, the cards an ambiguous name could be, close
    names for unknown ones. Nothing is saved."""
    parsed = deck_import.parse(body.text, body.game_id)
    matches = await deck_import.resolve(session, body.game_id, [line.name for line in parsed.lines])
    printings = await deck_import.resolve_printings(
        session,
        body.game_id,
        [
            (matches[line.name].cards[0].id, line.set_code, line.collector_number)
            for line in parsed.lines
            if line.set_code and len(matches[line.name].cards) == 1
        ],
    )
    fmt = FORMATS[GAMES[body.game_id][0]]
    lines = []
    for line in parsed.lines:
        match = matches[line.name]
        printing = None
        if len(match.cards) == 1:
            line.section = deck_rules.home_section(fmt, match.cards[0].attributes, line.section)
            status_, card, candidates = "resolved", _candidate(match.cards[0]), []
            found = printings.get((card.card_id, line.set_code or "", line.collector_number))
            if found is not None:
                printing = DeckImportPrintingOut(
                    id=found.id,
                    set_code=line.set_code or "",
                    collector_number=found.collector_number,
                )
        elif match.cards:
            status_, card, candidates = "ambiguous", None, [_candidate(c) for c in match.cards]
        else:
            status_, card, candidates = "unknown", None, [_candidate(c) for c in match.suggestions]
        lines.append(
            DeckImportLineOut(
                line=line.number,
                text=line.text,
                quantity=line.quantity,
                name=line.name,
                section=line.section,
                set_code=line.set_code,
                collector_number=line.collector_number,
                printing=printing,
                status=status_,
                card=card,
                candidates=candidates,
            )
        )
    return DeckImportPreviewOut(lines=lines, skipped=[text for _, text, _ in parsed.errors])


@router.post("/{deck_id}/import")
async def import_cards(
    deck_id: int, body: DeckImportIn, user: DecksUser, session: SessionDep
) -> DeckDetailOut:
    """Add the previewed cards (same card and section added up), or replace the
    decklist with them. Only the decklist changes: no copy is allocated."""
    deck = await _own(session, user, deck_id, lock=True)
    wanted: dict[tuple[int, str, int | None], int] = {}
    for entry in body.entries:
        key = (entry.card_id, entry.section, entry.printing_id)
        wanted[key] = wanted.get(key, 0) + entry.quantity
    card_ids = {card_id for card_id, _, _ in wanted}
    known = set(
        await session.scalars(
            select(Card.id).where(Card.id.in_(card_ids), Card.game_id == deck.game_id)
        )
    )
    if card_ids - known:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found")
    printing_ids = {p for _, _, p in wanted if p is not None}
    printing_cards = dict(
        (
            await session.execute(
                select(Printing.id, Printing.card_id).where(Printing.id.in_(printing_ids))
            )
        ).all()
    )
    if any(p is not None and printing_cards.get(p) != c for c, _, p in wanted):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Printing not found for this card")
    before = {e.card_id for e in deck.cards}
    current = {(e.card_id, e.section, e.printing_id): e.quantity for e in deck.cards}
    if body.replace:
        await session.execute(delete(DeckCard).where(DeckCard.deck_id == deck.id))
        current = {}
    for (card_id, section, printing_id), quantity in wanted.items():
        total = min(MAX_COPIES, current.get((card_id, section, printing_id), 0) + quantity)
        await decks.set_line(session, deck, card_id, section, printing_id, total)
    if body.replace:
        await decks.release_excess(session, deck, before | card_ids)
    deck.updated_at = func.now()
    await session.commit()
    return await _detail(session, user, deck_id)
