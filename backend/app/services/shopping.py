"""Shopping lists of the Decks module: the cards a deck misses (`decks.line_missing`), as
a check list to print or keep (.txt, .md, .pdf) or sent to the Android app
(`models.ShoppingList`)."""

import unicodedata
from dataclasses import dataclass
from datetime import date

from fpdf import FPDF

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


@dataclass
class ShoppingLine:
    card_id: int | None
    printing_id: int | None
    name: str
    # Name in the user's language, None when the same.
    translation: str | None
    set_code: str | None
    collector_number: str | None
    quantity: int
    bought: bool = False

    def label(self) -> str:
        """`Lightning Bolt (Foudre) · M10 146`"""
        text = self.name if not self.translation else f"{self.name} ({self.translation})"
        printing = " ".join(p for p in (self.set_code, self.collector_number) if p)
        return f"{text} · {printing}" if printing else text


def _words(lang: str) -> dict[str, str]:
    return WORDS.get(lang, WORDS["en"])


def _heading(name: str, lines: list[ShoppingLine], lang: str, day: date) -> tuple[str, str]:
    words = _words(lang)
    count = words["copies"].format(n=sum(line.quantity for line in lines))
    return f"{name} — {words['title']}", f"{day.isoformat()} · {count}"


def to_txt(name: str, lines: list[ShoppingLine], lang: str, day: date) -> str:
    title, sub = _heading(name, lines, lang, day)
    body = [f"[{'x' if line.bought else ' '}] {line.quantity} {line.label()}" for line in lines]
    return "\n".join([title, sub, "", *(body or [_words(lang)["none"]])]) + "\n"


def _md(text: str) -> str:
    """Text with Markdown's special characters escaped."""
    return "".join(f"\\{c}" if c in "\\`*_[]<>#|" else c for c in text)


def to_md(name: str, lines: list[ShoppingLine], lang: str, day: date) -> str:
    title, sub = _heading(name, lines, lang, day)
    body = [
        f"- [{'x' if line.bought else ' '}] {line.quantity} {_md(line.label())}" for line in lines
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


def to_pdf(name: str, lines: list[ShoppingLine], lang: str, day: date) -> bytes:
    """A4 page(s): title, date and count, then one line per card with a box to tick."""
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
    for line in lines:
        if pdf.will_page_break(7):
            pdf.add_page()
        x, y = pdf.get_x(), pdf.get_y()
        pdf.rect(x, y + 1.5, 4, 4)
        if line.bought:
            pdf.line(x + 0.8, y + 3.5, x + 1.8, y + 4.8)
            pdf.line(x + 1.8, y + 4.8, x + 3.4, y + 2.1)
        pdf.set_x(x + 7)
        pdf.cell(10, 7, str(line.quantity))
        pdf.cell(0, 7, _latin1(line.label()), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
