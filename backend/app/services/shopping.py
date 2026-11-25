"""Shopping lists (`models.ShoppingList`), for every user: what a source misses (a deck,
`decks.line_missing`; a followed set's missing printings) or cards added by hand, as a
check list ticked on the web and in the Android app, or as a file (.txt, .md, .pdf).

A linked list follows its source only when the user asks (`sync_source`): the cards and
copies come from the source again, ticks stay on what is still missing."""

import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import ShoppingEdition, ShoppingItem, ShoppingList

# The few words of the files, in the interface languages.
WORDS = {
    "en": {"title": "Shopping list", "copies": "{n} cards to get", "none": "Nothing to buy."},
    "fr": {"title": "Liste d'achats", "copies": "{n} cartes à trouver", "none": "Rien à acheter."},
    "de": {
        "title": "Einkaufsliste",
        "copies": "{n} Karten zu besorgen",
        "none": "Nichts zu kaufen.",
    },
    "es": {
        "title": "Lista de compras",
        "copies": "{n} cartas por conseguir",
        "none": "Nada que comprar.",
    },
}


@dataclass(frozen=True)
class Edition:
    printing_id: int | None
    set_code: str | None
    collector_number: str | None

    def label(self) -> str:
        return " ".join(p for p in (self.set_code, self.collector_number) if p)


@dataclass
class ShoppingLine:
    card_id: int | None
    name: str
    # Name in the user's language, None when the same.
    translation: str | None
    quantity: int
    # Accepted editions, none: any.
    editions: list[Edition] = field(default_factory=list)
    # Copies must be in this language / finish; None: any.
    language: str | None = None
    finish: str | None = None
    # Copies ticked as bought.
    bought: int = 0

    def key(self) -> tuple[object, ...]:
        """What the line asks for: the same key across refreshes keeps the ticks."""
        return _key(self.card_id, self.editions, self.language, self.finish)

    def label(self) -> str:
        """`Lightning Bolt (Foudre) · M10 146 / 2X2 117 · FR foil`"""
        text = self.name if not self.translation else f"{self.name} ({self.translation})"
        parts = [text]
        if printings := " / ".join(e.label() for e in self.editions if e.label()):
            parts.append(printings)
        if wanted := " ".join(p for p in ((self.language or "").upper(), self.finish) if p):
            parts.append(wanted)
        return " · ".join(parts)


def _key(
    card_id: int | None, editions: list[Edition], language: str | None, finish: str | None
) -> tuple[object, ...]:
    return (
        card_id,
        frozenset(e.printing_id or (e.set_code, e.collector_number) for e in editions),
        language,
        finish,
    )


def item_editions(item: ShoppingItem) -> list[Edition]:
    return [Edition(e.printing_id, e.set_code, e.collector_number) for e in item.editions]


def item_line(item: ShoppingItem) -> ShoppingLine:
    return ShoppingLine(
        card_id=item.card_id,
        name=item.name,
        translation=item.translation,
        quantity=item.quantity,
        editions=item_editions(item),
        language=item.language,
        finish=item.finish,
        bought=item.bought,
    )


def set_editions(item: ShoppingItem, editions: list[Edition]) -> None:
    item.editions = [
        ShoppingEdition(
            position=i,
            printing_id=e.printing_id,
            set_code=e.set_code,
            collector_number=e.collector_number,
        )
        for i, e in enumerate(editions)
    ]


def new_item(line: ShoppingLine, position: int, *, from_source: bool) -> ShoppingItem:
    item = ShoppingItem(
        position=position,
        card_id=line.card_id,
        name=line.name,
        translation=line.translation,
        language=line.language,
        finish=line.finish,
        quantity=line.quantity,
        bought=min(max(line.bought, 0), line.quantity),
        source_quantity=line.quantity if from_source else None,
    )
    set_editions(item, line.editions)
    return item


def refresh(found: ShoppingList, lines: list[ShoppingLine]) -> None:
    """The list's cards become the source's `lines` (items loaded). An item asking the
    same (`ShoppingLine.key`) keeps its ticks; when the source asks fewer copies, ticked
    copies go first (a bought copy reached the collection). Other items, those added by
    hand too, are removed. Refreshing again changes nothing."""
    old: dict[tuple[object, ...], ShoppingItem] = {}
    for item in found.items:
        old.setdefault(_key(item.card_id, item_editions(item), item.language, item.finish), item)
    items = []
    for position, line in enumerate(lines):
        item = old.pop(line.key(), None)
        if item is None:
            items.append(new_item(line, position, from_source=True))
            continue
        before = item.source_quantity if item.source_quantity is not None else item.quantity
        drop = max(0, before - line.quantity)
        item.bought = min(max(item.bought - drop, 0), line.quantity)
        item.quantity = item.source_quantity = line.quantity
        item.position = position
        item.name, item.translation = line.name, line.translation
        items.append(item)
    found.items = items
    found.updated_at = datetime.now(UTC)


SyncStatus = Literal["created", "updated", "deleted", "nothing"]


async def linked_list(
    session: AsyncSession, user_id: int, *, deck_id: int | None = None, binder_id: int | None = None
) -> ShoppingList | None:
    """The source's list, locked until the end of the transaction."""
    column = ShoppingList.deck_id if deck_id is not None else ShoppingList.binder_id
    return await session.scalar(
        select(ShoppingList)
        .where(ShoppingList.user_id == user_id, column == (deck_id or binder_id))
        .options(selectinload(ShoppingList.items))
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def sync_source(
    session: AsyncSession,
    user_id: int,
    *,
    game_id: str,
    name: str,
    lines: list[ShoppingLine],
    deck_id: int | None = None,
    binder_id: int | None = None,
) -> tuple[SyncStatus, ShoppingList | None]:
    """Create list / Update list of a deck or a followed set (one of `deck_id`,
    `binder_id`), not committed:

    - no list, nothing missing: "nothing", no list made;
    - no list: the list is made with what is missing ("created");
    - a list, something missing: rebuilt (`refresh`), same id and name ("updated");
    - a list, nothing missing: deleted ("deleted").

    One list per source even when two requests arrive together: the second one waits on
    the unique index, then updates the list the first one made."""
    found = await linked_list(session, user_id, deck_id=deck_id, binder_id=binder_id)
    if found is None:
        if not lines:
            return "nothing", None
        made = ShoppingList(
            user_id=user_id, deck_id=deck_id, binder_id=binder_id, game_id=game_id, name=name
        )
        made.items = [new_item(line, i, from_source=True) for i, line in enumerate(lines)]
        try:
            async with session.begin_nested():
                session.add(made)
        except IntegrityError:
            found = await linked_list(session, user_id, deck_id=deck_id, binder_id=binder_id)
            if found is None:
                raise
        else:
            return "created", made
    if not lines:
        await session.delete(found)
        return "deleted", None
    refresh(found, lines)
    return "updated", found


def _words(lang: str) -> dict[str, str]:
    return WORDS.get(lang, WORDS["en"])


def _boxes(line: ShoppingLine) -> str:
    """One box per copy, the bought ones ticked: `[x][ ][ ]`."""
    bought = min(max(line.bought, 0), line.quantity)
    return "[x]" * bought + "[ ]" * (line.quantity - bought)


def _heading(name: str, lines: list[ShoppingLine], lang: str, day: date) -> tuple[str, str]:
    words = _words(lang)
    count = words["copies"].format(n=sum(line.quantity for line in lines))
    return f"{name} — {words['title']}", f"{day.isoformat()} · {count}"


def to_txt(name: str, lines: list[ShoppingLine], lang: str, day: date) -> str:
    title, sub = _heading(name, lines, lang, day)
    body = [f"{_boxes(line)} {line.quantity} {line.label()}" for line in lines]
    return "\n".join([title, sub, "", *(body or [_words(lang)["none"]])]) + "\n"


def _md(text: str) -> str:
    """Text with Markdown's special characters escaped."""
    return "".join(f"\\{c}" if c in "\\`*_[]<>#|" else c for c in text)


def to_md(name: str, lines: list[ShoppingLine], lang: str, day: date) -> str:
    """A task list with one line per copy, so Markdown apps show a box to tick for each."""
    title, sub = _heading(name, lines, lang, day)
    body = [
        f"- [{'x' if copy < line.bought else ' '}] {_md(line.label())}"
        + (f" ({copy + 1}/{line.quantity})" if line.quantity > 1 else "")
        for line in lines
        for copy in range(line.quantity)
    ]
    return (
        "\n".join([f"# {_md(title)}", "", f"_{sub}_", "", *(body or [_words(lang)["none"]])]) + "\n"
    )


def _latin1(text: str) -> str:
    """The PDF's built-in fonts have Latin-1 only: other letters lose their accents (Œ
    becomes OE), the rest becomes "?"."""
    out = []
    for c in text.replace("—", "-").replace("·", "-").replace("Œ", "OE").replace("œ", "oe"):
        try:
            c.encode("latin-1")
            out.append(c)
        except UnicodeEncodeError:
            plain = unicodedata.normalize("NFKD", c).encode("latin-1", "ignore").decode("latin-1")
            out.append(plain or "?")
    return "".join(out)


# PDF boxes: a row holds this many copies, one box every `BOX_STEP` mm.
BOXES_PER_ROW = 10
BOX_STEP = 5.5


def to_pdf(name: str, lines: list[ShoppingLine], lang: str, day: date) -> bytes:
    """A4 page(s): title, date and count, then one line per card with a box to tick per
    copy (rows of `BOXES_PER_ROW`, the name after the first row)."""
    title, sub = _heading(name, lines, lang, day)
    pdf = FPDF(format="A4")
    pdf.set_title(_latin1(title))
    pdf.set_creator("Zukan")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 8, _latin1(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100)
    pdf.cell(0, 6, _latin1(sub), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 11)
    if not lines:
        pdf.cell(0, 7, _latin1(_words(lang)["none"]), new_x="LMARGIN", new_y="NEXT")
    widest = min(max((line.quantity for line in lines), default=1), BOXES_PER_ROW)
    for line in lines:
        rows = -(-line.quantity // BOXES_PER_ROW)
        if pdf.will_page_break(7 * rows):
            pdf.add_page()
        x, y = pdf.get_x(), pdf.get_y()
        for copy in range(line.quantity):
            bx = x + (copy % BOXES_PER_ROW) * BOX_STEP
            by = y + (copy // BOXES_PER_ROW) * 7
            pdf.rect(bx, by + 1.5, 4, 4)
            if copy < line.bought:
                pdf.line(bx + 0.8, by + 3.5, bx + 1.8, by + 4.8)
                pdf.line(bx + 1.8, by + 4.8, bx + 3.4, by + 2.1)
        pdf.set_x(x + widest * BOX_STEP + 2)
        pdf.cell(10, 7, str(line.quantity))
        pdf.cell(0, 7, _latin1(line.label()), new_x="LMARGIN", new_y="NEXT")
        if rows > 1:
            pdf.set_y(y + 7 * rows)
    return bytes(pdf.output())
