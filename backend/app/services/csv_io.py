"""Collection CSV import/export.

Generic format, one row per collection item:
    game,set_code,collector_number,name,language,finish,condition,quantity,manual_price,notes

`collector_number` is the printed number, or the provider's printing id for games
without one (Sorcery). `name` is informational on import. Semicolon or tab separated
files (spreadsheet exports in many locales) are accepted too.

Text that spreadsheets would read as a formula (starting with = + - @, possibly after
spaces or control characters) is exported behind a `'`, which the import removes again.
"""

import csv
import io
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.games.base import group_of, registry
from app.models import Card, CardSet, CollectionItem, Condition, Printing
from app.services import collection
from app.services.collection import StockError, Variant

COLUMNS = [
    "game",
    "set_code",
    "collector_number",
    "name",
    "language",
    "finish",
    "condition",
    "quantity",
    "manual_price",
    "notes",
]
REQUIRED = {"game", "set_code", "collector_number", "quantity"}
MAX_ROWS = 50_000
# Same limits as the item edit form (`api.collection.ItemUpdateIn`).
MAX_QUANTITY = 100_000
MAX_NOTES = 1000
_FORMULA_START = ("=", "+", "-", "@")
# Spaces and control characters spreadsheets skip before a formula.
_BLANKS = "".join(map(chr, range(33)))


def _is_formula(text: str) -> bool:
    return text.startswith(("\t", "\r")) or text.lstrip(_BLANKS).startswith(_FORMULA_START)


def spreadsheet_text(text: str) -> str:
    """`text` kept as text by spreadsheets: a formula gets a leading `'`."""
    return f"'{text}" if _is_formula(text) else text


def from_spreadsheet_text(text: str) -> str:
    """Undo `spreadsheet_text`."""
    return text[1:] if text.startswith("'") and _is_formula(text[1:]) else text


async def export_csv(session: AsyncSession, user_id: int, game_id: str | None) -> str:
    query = (
        select(CollectionItem, Printing, CardSet, Card)
        .join(Printing, CollectionItem.printing_id == Printing.id)
        .join(CardSet, Printing.set_id == CardSet.id)
        .join(Card, Printing.card_id == Card.id)
        .where(CollectionItem.user_id == user_id, CollectionItem.quantity > 0)
        .order_by(CardSet.game_id, CardSet.code, Printing.collector_number, Card.name)
    )
    if game_id:
        query = query.where(CardSet.game_id == game_id)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for item, printing, card_set, card in await session.execute(query):
        text = [
            card_set.game_id,
            card_set.code,
            printing.collector_number or printing.external_id,
            card.name,
            item.language,
            item.finish,
            item.condition,
        ]
        writer.writerow(
            [
                *map(spreadsheet_text, text),
                item.quantity,
                "" if item.manual_price is None else item.manual_price,
                spreadsheet_text(item.notes or ""),
            ]
        )
    return out.getvalue()


@dataclass
class RowError:
    line: int
    message: str


@dataclass
class ImportReport:
    rows: int = 0
    imported: int = 0
    errors: list[RowError] = field(default_factory=list)


@dataclass
class _Row:
    line: int
    printing: Printing
    game_id: str
    variant: Variant
    quantity: int
    manual_price: Decimal | None
    notes: str | None


def _reader(text: str) -> csv.DictReader:
    # Only the delimiter is guessed from the header: quoting stays the usual one (quotes
    # doubled inside quoted cells), which the header alone does not show.
    try:
        delimiter = csv.Sniffer().sniff(text.split("\n", 1)[0], delimiters=",;\t").delimiter
    except csv.Error:
        delimiter = ","
    return csv.DictReader(io.StringIO(text), delimiter=delimiter)


class _PrintingLookup:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.cache: dict[tuple[str, str, str], list[Printing]] = {}

    async def find(self, game_id: str, set_code: str, number: str) -> list[Printing]:
        key = (game_id, set_code.casefold(), number)
        if key not in self.cache:
            self.cache[key] = list(
                await self.session.scalars(
                    select(Printing)
                    .join(CardSet)
                    .where(
                        CardSet.game_id == game_id,
                        or_(
                            func.lower(CardSet.code) == set_code.casefold(),
                            CardSet.external_id == set_code,
                        ),
                        or_(Printing.collector_number == number, Printing.external_id == number),
                    )
                    .options(selectinload(Printing.set))
                )
            )
        return self.cache[key]


async def _parse(
    session: AsyncSession, text: str, set_mode: bool, report: ImportReport
) -> list[_Row]:
    reader = _reader(text)
    try:
        missing = REQUIRED - set(reader.fieldnames or [])
    except csv.Error as exc:
        report.errors.append(RowError(1, f"Invalid CSV: {exc}"))
        return []
    if missing:
        report.errors.append(RowError(1, f"Missing columns: {', '.join(sorted(missing))}"))
        return []
    lookup = _PrintingLookup(session)
    games = registry()
    rows: list[_Row] = []
    while True:
        try:
            raw = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            report.errors.append(RowError(reader.line_num, f"Invalid CSV: {exc}"))
            break
        line = reader.line_num
        report.rows += 1
        if report.rows > MAX_ROWS:
            report.errors.append(RowError(line, f"More than {MAX_ROWS} rows"))
            break
        value = {k.strip(): from_spreadsheet_text((v or "").strip()) for k, v in raw.items() if k}
        game_id = value["game"].lower()
        if game_id not in games:
            report.errors.append(RowError(line, f"Unknown game {value['game']!r}"))
            continue
        try:
            quantity = int(value["quantity"])
            price = (
                Decimal(value["manual_price"].replace(",", "."))
                if value.get("manual_price")
                else None
            )
        except (ValueError, InvalidOperation):
            report.errors.append(RowError(line, "Invalid quantity or price"))
            continue
        # Not a number (NaN), infinite, negative, too large or finer than a cent.
        if price is not None and (
            not price.is_finite()
            or not (0 <= price < 10**10)
            or int(price.as_tuple().exponent) < -2
        ):
            report.errors.append(RowError(line, f"Invalid price {value['manual_price']}"))
            continue
        if (quantity < 0 if set_mode else quantity == 0) or abs(quantity) > MAX_QUANTITY:
            report.errors.append(RowError(line, f"Invalid quantity {quantity}"))
            continue
        if any("\x00" in v for v in value.values()):
            report.errors.append(RowError(line, "Invalid character (NUL)"))
            continue
        if len(value.get("notes") or "") > MAX_NOTES:
            report.errors.append(RowError(line, f"Notes longer than {MAX_NOTES} characters"))
            continue
        matches = await lookup.find(game_id, value["set_code"], value["collector_number"])
        if not matches and game_id == group_of(game_id):
            # Files from before 0.17.0 name one game for every market ("pokemon" for a
            # Japanese set): the printing may be another game's of the group.
            for other in games:
                if other != game_id and group_of(other) == game_id:
                    found = await lookup.find(other, value["set_code"], value["collector_number"])
                    if found:
                        game_id, matches = other, found
                        break
        if len(matches) != 1:
            problem = "No printing" if not matches else "Several printings"
            report.errors.append(
                RowError(
                    line,
                    f"{problem} for set {value['set_code']!r} number {value['collector_number']!r}",
                )
            )
            continue
        printing = matches[0]
        provider = games[game_id]
        variant = Variant(
            finish=value.get("finish") or (printing.finishes or [provider.finishes[0].code])[0],
            condition=(value.get("condition") or Condition.NM).upper(),
            language=value.get("language") or (printing.languages or ["en"])[0],
        )
        try:
            collection.check_variant(game_id, printing, variant)
        except StockError as exc:
            report.errors.append(RowError(line, str(exc)))
            continue
        rows.append(
            _Row(line, printing, game_id, variant, quantity, price, value.get("notes") or None)
        )
    return rows


async def import_csv(
    session: AsyncSession, user_id: int, text: str, set_mode: bool, dry_run: bool
) -> ImportReport:
    """Validate every row first; import only when the whole file is valid.

    Default mode adds the quantities; `set_mode` makes stored quantities equal to them."""
    report = ImportReport()
    rows = await _parse(session, text, set_mode, report)
    if report.errors or dry_run:
        return report
    for row in rows:
        if set_mode:
            item = await session.scalar(
                select(CollectionItem).where(
                    CollectionItem.user_id == user_id,
                    CollectionItem.printing_id == row.printing.id,
                    CollectionItem.finish == row.variant.finish,
                    CollectionItem.condition == row.variant.condition,
                    CollectionItem.language == row.variant.language,
                )
            )
            delta = row.quantity - (item.quantity if item else 0)
        else:
            delta = row.quantity
        if delta:
            try:
                item, _ = await collection.adjust(
                    session, user_id, row.printing, row.variant, delta, "import", row.game_id
                )
            except StockError as exc:
                report.errors.append(RowError(row.line, str(exc)))
                await session.rollback()
                report.imported = 0
                return report
        if item is not None and (row.manual_price is not None or row.notes):
            if row.manual_price is not None:
                item.manual_price = row.manual_price
            if row.notes:
                item.notes = row.notes
        report.imported += 1
    await session.commit()
    return report
