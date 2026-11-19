"""Decks module (`app.modules`): decklists checked against their format's rules
(`services.deck_rules`), plain-text import (`services.deck_import`), and owned copies
allocated to decks (`services.decks`). Magic: The Gathering and the Pokémon TCG.

Editing a decklist or importing one never changes the collection or its availability:
only allocating does, and allocating never changes owned quantities."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from app.api.catalog import load_names, show_card, show_printing
from app.api.collection import copy_image
from app.api.deps import SessionDep
from app.models import Card, CollectionItem, Deck, DeckAllocation, DeckCard, Printing, User
from app.modules import require_module
from app.services import deck_import, deck_rules, decks
from app.services.deck_rules import FORMATS, GAMES, Leader, Rules, Section

router = APIRouter(prefix="/decks", tags=["decks"])

DecksUser = require_module("decks")

# Every key of `deck_rules.FORMATS` (a Literal so the OpenAPI schema lists them).
FormatId = Literal[tuple(FORMATS)]  # type: ignore[valid-type]
GameId = Literal[tuple(GAMES)]  # type: ignore[valid-type]
MAX_COPIES = 250


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
    # Rule set: "mtg" (Magic) or "pokemon".
    rules: Rules


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


class DeckOut(BaseModel):
    id: int
    game_id: str
    name: str
    format: str
    # Main deck with commanders, and sideboard.
    card_count: int
    sideboard_count: int
    errors: int
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


class DeckEntryOut(BaseModel):
    card_id: int
    name: str
    translation: str | None = None
    # The allocated copy's picture (the one most copies come from), else the card's.
    image: str | None
    colors: list[str]
    mana_cost: str | None
    type_line: str | None
    # Card type group shown in the list (Creature, Land... / Pokémon, Supporter...).
    group: str
    # Copies asked for per section.
    quantities: dict[str, int]
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
    section: Section = "main"
    # 0 removes the card from the section.
    quantity: int = Field(ge=0, le=MAX_COPIES)


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


class DeckImportLineOut(BaseModel):
    line: int
    text: str
    quantity: int
    name: str
    section: Section
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


def _groups(game_id: str) -> tuple[str, ...]:
    return (*(GROUPS if game_id == "mtg" else POKEMON_GROUPS), "Other")


def _group(card: Card) -> str:
    if card.game_id != "mtg":
        category = card.attributes.get("category")
        if category in ("Pokemon", "Pokémon"):
            return "Pokémon"
        if category == "Trainer":
            return _TRAINER_GROUPS.get(card.attributes.get("trainerType") or "", "Trainer")
        return "Energy" if category == "Energy" else "Other"
    types = card.attributes.get("types") or []
    # Artifact creatures are creatures, artifact lands are lands.
    if "Land" in types and "Creature" not in types:
        return "Land"
    return next((g for g in GROUPS if g in types), "Other")


def _candidate(card: Card) -> DeckCandidateOut:
    return DeckCandidateOut(
        card_id=card.id, name=card.name, type_line=card.attributes.get("type_line")
    )


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
    return [
        deck_rules.Entry(
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
        for e in deck.cards
    ]


async def _check(
    session: SessionDep, deck: Deck
) -> tuple[deck_rules.Report, list[deck_rules.Entry]]:
    entries = _rule_entries(deck, await _rule_printings(session, [deck]))
    return deck_rules.check(deck.format, entries), entries


def _item_image(printing: Printing, language: str, ui_lang: str) -> str | None:
    """Picture of a collection copy (set loaded), as the collection shows it."""
    _, picked = show_printing(printing, {}, {}, ui_lang)
    return copy_image(printing, language, picked)


async def _allocated_images(session: SessionDep, deck: Deck, ui_lang: str) -> dict[int, str]:
    """Per card, the picture of the copy most of its allocated copies come from."""
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
    shown: dict[int, str] = {}
    for allocation in allocations:
        item = allocation.item
        card_id = item.printing.card_id
        if card_id not in shown and (image := _item_image(item.printing, item.language, ui_lang)):
            shown[card_id] = image
    return shown


def _deck_out(deck: Deck, report: deck_rules.Report) -> DeckOut:
    count = sum(e.quantity for e in deck.cards if e.section != "sideboard")
    return DeckOut(
        id=deck.id,
        game_id=deck.game_id,
        name=deck.name,
        format=deck.format,
        card_count=count,
        sideboard_count=sum(e.quantity for e in deck.cards if e.section == "sideboard"),
        errors=sum(1 for i in report.issues if i.level == "error"),
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
        .options(selectinload(Deck.cards).selectinload(DeckCard.card))
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
    allocated_images = await _allocated_images(session, deck, user.language)
    entries = []
    for card_id in card_ids:
        card = cards[card_id]
        shown = show_card(card, card_names, printing_names, user.language)
        counts = stock[card_id]
        quantities = {e.section: e.quantity for e in deck.cards if e.card_id == card_id}
        entries.append(
            DeckEntryOut(
                card_id=card_id,
                name=shown.name.name,
                translation=shown.name.translation,
                image=allocated_images.get(card_id, shown.image),
                colors=card.colors,
                mana_cost=card.attributes.get("mana_cost")
                or " // ".join(
                    f["mana_cost"] for f in card.attributes.get("faces", []) if f.get("mana_cost")
                )
                or None,
                type_line=card.attributes.get("type_line"),
                group=_group(card),
                quantities=quantities,
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
    return DeckDetailOut(
        deck=_deck_out(deck, report),
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


@router.get("/formats")
async def list_formats(_: DecksUser) -> list[DeckGameOut]:
    """Games and formats decks can be built for."""
    return [
        DeckGameOut(
            game_id=game_id,
            formats=[DeckFormatOut(**FORMATS[f].__dict__) for f in formats],
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
    return [_deck_out(d, deck_rules.check(d.format, _rule_entries(d, printings))) for d in found]


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
    """Set the copies of a card in a section (0 removes it). Copies allocated beyond the
    deck's new total are released; the collection is not changed."""
    deck = await _own(session, user, deck_id, lock=True)
    await _card(session, deck, body.card_id)
    await _set_quantity(session, deck, body.card_id, body.section, body.quantity)
    await decks.release_excess(session, deck, [body.card_id])
    deck.updated_at = func.now()
    await session.commit()
    return await _detail(session, user, deck_id)


async def _set_quantity(
    session: SessionDep, deck: Deck, card_id: int, section: str, quantity: int
) -> None:
    if quantity == 0:
        await session.execute(
            delete(DeckCard).where(
                DeckCard.deck_id == deck.id,
                DeckCard.card_id == card_id,
                DeckCard.section == section,
            )
        )
        return
    stmt = insert(DeckCard).values(
        deck_id=deck.id, card_id=card_id, section=section, quantity=quantity
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[DeckCard.deck_id, DeckCard.card_id, DeckCard.section],
            set_={"quantity": quantity},
        )
    )


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


@router.post("/import/preview")
async def import_preview(
    body: DeckImportPreviewIn, _: DecksUser, session: SessionDep
) -> DeckImportPreviewOut:
    """Read a plain-text decklist ("4 Lightning Bolt", "Commander" / "Sideboard"
    headers): the card each line names, the cards an ambiguous name could be, close
    names for unknown ones. Nothing is saved."""
    parsed = deck_import.parse(body.text, body.game_id)
    matches = await deck_import.resolve(session, body.game_id, [line.name for line in parsed.lines])
    lines = []
    for line in parsed.lines:
        match = matches[line.name]
        if len(match.cards) == 1:
            status_, card, candidates = "resolved", _candidate(match.cards[0]), []
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
    wanted: dict[tuple[int, str], int] = {}
    for entry in body.entries:
        key = (entry.card_id, entry.section)
        wanted[key] = wanted.get(key, 0) + entry.quantity
    card_ids = {card_id for card_id, _ in wanted}
    known = set(
        await session.scalars(
            select(Card.id).where(Card.id.in_(card_ids), Card.game_id == deck.game_id)
        )
    )
    if card_ids - known:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found")
    before = {e.card_id for e in deck.cards}
    current = {(e.card_id, e.section): e.quantity for e in deck.cards}
    if body.replace:
        await session.execute(delete(DeckCard).where(DeckCard.deck_id == deck.id))
        current = {}
    for (card_id, section), quantity in wanted.items():
        total = min(MAX_COPIES, current.get((card_id, section), 0) + quantity)
        await _set_quantity(session, deck, card_id, section, total)
    if body.replace:
        await decks.release_excess(session, deck, before | card_ids)
    deck.updated_at = func.now()
    await session.commit()
    return await _detail(session, user, deck_id)
