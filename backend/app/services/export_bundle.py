"""Export bundle: the collection and the optional modules' data in one zip.

A zip holds `manifest.json` and one CSV per part (`PARTS`):
- `cards.csv`: the collection, the format of `services.csv_io`;
- `binder_sets.csv`: the sets followed in the Binder, with their language and finish;
- `decks.csv`, `deck_cards.csv`, `deck_allocations.csv`: decks, their lines, and the
  owned copies allocated to them (a collection item named like in `cards.csv`).

Rows name cards, sets and printings by the sources' ids (and set code and number), never
by Zukan's database ids, so a bundle imports on another server. Decks are named by a
`deck` reference local to the bundle. Importing checks every file first and writes
nothing if any row is invalid; the parts of modules the user has not enabled are
refused.
"""

import csv
import io
import json
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import __version__
from app.games.base import registry
from app.models import (
    BinderSet,
    Card,
    CardSet,
    CollectionItem,
    Condition,
    Deck,
    DeckAllocation,
    DeckCard,
    Printing,
)
from app.services import csv_io, deck_rules, decks
from app.services.csv_io import ImportReport, RowError, from_spreadsheet_text, spreadsheet_text
from app.services.decks import AllocationError

FORMAT = "zukan-export"
VERSION = 1
# Parts and the module they need (None: always there).
PARTS: dict[str, str | None] = {"cards": None, "binder": "binder", "decks": "decks"}
FILES = {
    "cards": ("cards.csv",),
    "binder": ("binder_sets.csv",),
    "decks": ("decks.csv", "deck_cards.csv", "deck_allocations.csv"),
}
MANIFEST = "manifest.json"
KNOWN_FILES = {MANIFEST, *(name for names in FILES.values() for name in names)}
# Uncompressed size of one file and of the whole bundle (a zip bomb stops there).
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_DECKS = 1000
MAX_DECK_ROWS = 50_000
MAX_NAME = 100
MAX_COPIES = 250

BINDER_COLUMNS = ["game", "set_code", "set_id", "set_name", "language", "finish"]
DECK_COLUMNS = ["deck", "game", "name", "format"]
DECK_CARD_COLUMNS = [
    "deck",
    "game",
    "card_id",
    "name",
    "section",
    "quantity",
    "set_code",
    "collector_number",
    "set_id",
    "printing_id",
]
ALLOCATION_COLUMNS = [
    "deck",
    "game",
    "set_code",
    "collector_number",
    "name",
    "language",
    "finish",
    "condition",
    "quantity",
    "set_id",
    "printing_id",
]


class BundleError(Exception):
    """The upload is not a bundle that can be read (not a zip, unknown files, too big)."""


def is_zip(data: bytes) -> bool:
    return data.startswith(b"PK\x03\x04")


def _csv(header: list[str], rows: Iterable[list[object]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(
            ["" if v is None else spreadsheet_text(v) if isinstance(v, str) else v for v in row]
        )
    return out.getvalue()


async def _binder_csv(session: AsyncSession, user_id: int, game_id: str | None) -> str:
    query = (
        select(BinderSet, CardSet)
        .join(CardSet, BinderSet.set_id == CardSet.id)
        .where(BinderSet.user_id == user_id)
        .order_by(CardSet.game_id, CardSet.code)
    )
    if game_id:
        query = query.where(CardSet.game_id == game_id)
    rows = [
        [s.game_id, s.code, s.external_id, s.name, b.language, b.finish]
        for b, s in await session.execute(query)
    ]
    return _csv(BINDER_COLUMNS, rows)


async def _decks_csv(
    session: AsyncSession, user_id: int, game_id: str | None
) -> tuple[str, str, str]:
    query = (
        select(Deck)
        .where(Deck.user_id == user_id)
        .order_by(Deck.game_id, Deck.name, Deck.id)
        .options(
            selectinload(Deck.cards).selectinload(DeckCard.card),
            selectinload(Deck.cards).selectinload(DeckCard.printing).selectinload(Printing.set),
        )
    )
    if game_id:
        query = query.where(Deck.game_id == game_id)
    found = list(await session.scalars(query))
    ref = {deck.id: str(n) for n, deck in enumerate(found, start=1)}
    deck_rows = [[ref[d.id], d.game_id, d.name, d.format] for d in found]
    line_rows = []
    for deck in found:
        for line in sorted(deck.cards, key=lambda e: (e.section, e.card.name, e.id)):
            printing = line.printing
            line_rows.append(
                [
                    ref[deck.id],
                    deck.game_id,
                    line.card.external_id,
                    line.card.name,
                    line.section,
                    line.quantity,
                    printing.set.code if printing else None,
                    (printing.collector_number or printing.external_id) if printing else None,
                    printing.set.external_id if printing else None,
                    printing.external_id if printing else None,
                ]
            )
    allocations = await session.execute(
        select(DeckAllocation, CollectionItem, Printing, CardSet, Card)
        .join(CollectionItem, DeckAllocation.item_id == CollectionItem.id)
        .join(Printing, CollectionItem.printing_id == Printing.id)
        .join(CardSet, Printing.set_id == CardSet.id)
        .join(Card, Printing.card_id == Card.id)
        .where(DeckAllocation.deck_id.in_(ref))
        .order_by(DeckAllocation.deck_id, Card.name, DeckAllocation.id)
    )
    allocation_rows = [
        [
            ref[a.deck_id],
            s.game_id,
            s.code,
            p.collector_number or p.external_id,
            c.name,
            i.language,
            i.finish,
            i.condition,
            a.quantity,
            s.external_id,
            p.external_id,
        ]
        for a, i, p, s, c in allocations
    ]
    return (
        _csv(DECK_COLUMNS, deck_rows),
        _csv(DECK_CARD_COLUMNS, line_rows),
        _csv(ALLOCATION_COLUMNS, allocation_rows),
    )


async def export_zip(
    session: AsyncSession, user_id: int, game_id: str | None, parts: list[str]
) -> bytes:
    """The bundle of these parts (checked by the caller against the user's modules)."""
    files: dict[str, str] = {}
    if "cards" in parts:
        files["cards.csv"] = await csv_io.export_csv(session, user_id, game_id)
    if "binder" in parts:
        files["binder_sets.csv"] = await _binder_csv(session, user_id, game_id)
    if "decks" in parts:
        names = FILES["decks"]
        files.update(zip(names, await _decks_csv(session, user_id, game_id), strict=True))
    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "zukan": __version__,
        "exported": date.today().isoformat(),
        "game": game_id,
        "parts": [p for p in PARTS if p in parts],
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(MANIFEST, json.dumps(manifest, indent=2) + "\n")
        for name, text in files.items():
            bundle.writestr(name, text)
    return out.getvalue()


def read_zip(data: bytes) -> dict[str, str]:
    """The bundle's files as text, checked: known names only, sizes bounded (the actual
    bytes read, not the sizes the zip claims), UTF-8."""
    try:
        bundle = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise BundleError("Not a valid zip file") from exc
    with bundle:
        entries = [e for e in bundle.infolist() if not e.is_dir()]
        if len(entries) > len(KNOWN_FILES):
            raise BundleError("Too many files in the zip")
        unknown = sorted(e.filename for e in entries if e.filename not in KNOWN_FILES)
        if unknown:
            raise BundleError(f"Unknown files in the zip: {', '.join(unknown)}")
        files: dict[str, str] = {}
        total = 0
        for entry in entries:
            try:
                with bundle.open(entry) as stream:
                    raw = stream.read(MAX_FILE_BYTES + 1)
            except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
                raise BundleError(f"{entry.filename} cannot be read: {exc}") from exc
            total += len(raw)
            if len(raw) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                raise BundleError("Files in the zip are too large")
            try:
                files[entry.filename] = raw.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise BundleError(f"{entry.filename} must be UTF-8 text") from exc
    if MANIFEST in files:
        try:
            manifest = json.loads(files[MANIFEST])
        except ValueError as exc:
            raise BundleError("manifest.json is not valid JSON") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
            raise BundleError("manifest.json is not a Zukan export")
        if not isinstance(manifest.get("version"), int) or manifest["version"] > VERSION:
            raise BundleError("This export comes from a newer Zukan: update this server first")
    if not set(files) - {MANIFEST}:
        raise BundleError("The zip holds no file to import")
    return files


def parts_of(files: dict[str, str]) -> list[str]:
    return [part for part, names in FILES.items() if any(n in files for n in names)]


@dataclass
class BundleReport(ImportReport):
    # Rows written (or valid, on a dry run) per file.
    counts: dict[str, int] = field(default_factory=dict)


def _rows(
    name: str, text: str, required: set[str], report: BundleReport, limit: int = MAX_DECK_ROWS
) -> list[tuple[int, dict[str, str]]]:
    """The file's rows (line number, cleaned values), or [] with an error."""
    reader = csv_io.csv_reader(text)
    try:
        missing = required - set(reader.fieldnames or [])
    except csv.Error as exc:
        report.errors.append(
            RowError(1, f"Invalid CSV: {exc}", name, "invalid_csv", {"detail": str(exc)})
        )
        return []
    if missing:
        report.errors.append(
            RowError(
                1,
                f"Missing columns: {', '.join(sorted(missing))}",
                name,
                "missing_columns",
                {"columns": ", ".join(sorted(missing))},
            )
        )
        return []
    rows = []
    try:
        for raw in reader:
            if len(rows) >= limit:
                report.errors.append(
                    RowError(
                        reader.line_num,
                        f"More than {limit} rows",
                        name,
                        "too_many_rows",
                        {"max": limit},
                    )
                )
                break
            value = {
                k.strip(): from_spreadsheet_text((v or "").strip()) for k, v in raw.items() if k
            }
            if any("\x00" in v for v in value.values()):
                report.errors.append(
                    RowError(reader.line_num, "Invalid character (NUL)", name, "nul_character")
                )
                continue
            rows.append((reader.line_num, value))
    except csv.Error as exc:
        report.errors.append(
            RowError(
                reader.line_num, f"Invalid CSV: {exc}", name, "invalid_csv", {"detail": str(exc)}
            )
        )
    return rows


@dataclass
class _Follow:
    line: int
    set_id: int
    language: str | None
    finish: str | None


async def _set_of(session: AsyncSession, game_id: str, value: dict[str, str]) -> list[CardSet]:
    if value.get("set_id"):
        found = await session.scalar(
            select(CardSet).where(
                CardSet.game_id == game_id, CardSet.external_id == value["set_id"]
            )
        )
        if found is not None:
            return [found]
    code = value.get("set_code") or ""
    return list(
        await session.scalars(
            select(CardSet).where(
                CardSet.game_id == game_id, func.lower(CardSet.code) == code.casefold()
            )
        )
    )


async def _parse_binder(session: AsyncSession, text: str, report: BundleReport) -> list[_Follow]:
    from app.api.catalog import set_languages  # the API module imports services

    name = "binder_sets.csv"
    follows: list[_Follow] = []
    seen: set[int] = set()
    for line, value in _rows(name, text, {"game", "set_code"}, report):
        game_id = value["game"].lower()
        if game_id not in registry():
            report.errors.append(
                RowError(
                    line,
                    f"Unknown game {value['game']!r}",
                    name,
                    "unknown_game",
                    {"game": value["game"]},
                )
            )
            continue
        sets = await _set_of(session, game_id, value)
        if len(sets) != 1:
            problem = "No set" if not sets else "Several sets"
            report.errors.append(
                RowError(
                    line,
                    f"{problem} {value['set_code']!r}",
                    name,
                    "set_not_found" if not sets else "set_ambiguous",
                    {"set": value["set_code"]},
                )
            )
            continue
        card_set = sets[0]
        language = value.get("language") or None
        finish = value.get("finish") or None
        if language and language not in (await set_languages(session, [card_set.id])).get(
            card_set.id, set()
        ):
            report.errors.append(
                RowError(
                    line,
                    f"No printing of this set in {language!r}",
                    name,
                    "set_language_missing",
                    {"language": language},
                )
            )
            continue
        if finish and finish not in set(
            await session.scalars(
                select(func.unnest(Printing.finishes))
                .where(Printing.set_id == card_set.id)
                .distinct()
            )
        ):
            report.errors.append(
                RowError(
                    line,
                    f"No printing of this set in {finish!r}",
                    name,
                    "set_finish_missing",
                    {"finish": finish},
                )
            )
            continue
        if card_set.id in seen:
            report.errors.append(RowError(line, "Set listed twice", name, "set_twice"))
            continue
        seen.add(card_set.id)
        follows.append(_Follow(line, card_set.id, language, finish))
    return follows


@dataclass
class _DeckRow:
    line: int
    ref: str
    game_id: str
    name: str
    format: str
    # (card id, section, printing id or None) -> copies.
    lines: dict[tuple[int, str, int | None], int] = field(default_factory=dict)
    # (line in deck_allocations.csv, printing, finish, condition, language, copies).
    allocations: list[tuple[int, Printing, str, str, str, int]] = field(default_factory=list)


async def _parse_decks(
    session: AsyncSession, files: dict[str, str], report: BundleReport
) -> dict[str, _DeckRow]:
    found: dict[str, _DeckRow] = {}
    name = "decks.csv"
    if name not in files:
        report.errors.append(RowError(1, "decks.csv is missing", name, "decks_file_missing"))
        return found
    for line, value in _rows(name, files[name], set(DECK_COLUMNS), report, MAX_DECKS):
        game_id, deck_format = value["game"].lower(), value["format"]
        title = " ".join(value["name"].split())
        if not value["deck"]:
            report.errors.append(
                RowError(line, "No deck reference", name, "deck_reference_missing")
            )
        elif value["deck"] in found:
            report.errors.append(
                RowError(
                    line,
                    f"Deck {value['deck']!r} listed twice",
                    name,
                    "deck_twice",
                    {"deck": value["deck"]},
                )
            )
        elif game_id not in deck_rules.GAMES:
            report.errors.append(
                RowError(
                    line,
                    f"No decks for game {value['game']!r}",
                    name,
                    "game_without_decks",
                    {"game": value["game"]},
                )
            )
        elif deck_format not in deck_rules.GAMES[game_id]:
            report.errors.append(
                RowError(
                    line,
                    f"{deck_format!r} is not a format of {game_id}",
                    name,
                    "format_unknown",
                    {"format": deck_format, "game": game_id},
                )
            )
        elif not 0 < len(title) <= MAX_NAME:
            report.errors.append(
                RowError(
                    line,
                    f"Deck names have 1 to {MAX_NAME} characters",
                    name,
                    "deck_name_length",
                    {"max": MAX_NAME},
                )
            )
        else:
            found[value["deck"]] = _DeckRow(line, value["deck"], game_id, title, deck_format)

    name = "deck_cards.csv"
    cards: dict[tuple[str, str], Card | None] = {}
    lookup = csv_io.PrintingLookup(session)
    for line, value in _rows(
        name, files.get(name, ""), {"deck", "card_id", "section", "quantity"}, report
    ):
        deck = found.get(value["deck"])
        if deck is None:
            report.errors.append(
                RowError(
                    line,
                    f"Unknown deck {value['deck']!r}",
                    name,
                    "deck_unknown",
                    {"deck": value["deck"]},
                )
            )
            continue
        sections = {s for s, _ in deck_rules.FORMATS[deck.format].sections}
        if value["section"] not in sections:
            report.errors.append(
                RowError(
                    line,
                    f"No section {value['section']!r} in {deck.format}",
                    name,
                    "section_unknown",
                    {"section": value["section"], "format": deck.format},
                )
            )
            continue
        try:
            quantity = int(value["quantity"])
        except ValueError:
            quantity = 0
        if not 0 < quantity <= MAX_COPIES:
            report.errors.append(
                RowError(
                    line,
                    f"Invalid quantity {value['quantity']!r}",
                    name,
                    "invalid_quantity",
                    {"quantity": value["quantity"]},
                )
            )
            continue
        key = (deck.game_id, value["card_id"])
        if key not in cards:
            cards[key] = await session.scalar(
                select(Card).where(Card.game_id == deck.game_id, Card.external_id == key[1])
            )
        card = cards[key]
        if card is None:
            label = value.get("name") or value["card_id"]
            report.errors.append(
                RowError(
                    line,
                    f"No card {label!r} in {deck.game_id}",
                    name,
                    "card_not_found",
                    {"card": label, "game": deck.game_id},
                )
            )
            continue
        printing_id = None
        if value.get("printing_id") or value.get("set_code"):
            _, matches = await lookup.resolve(
                deck.game_id,
                {
                    "set_id": value.get("set_id", ""),
                    "printing_id": value.get("printing_id", ""),
                    "set_code": value.get("set_code", ""),
                    "collector_number": value.get("collector_number", ""),
                },
            )
            matches = [p for p in matches if p.card_id == card.id]
            if len(matches) != 1:
                report.errors.append(
                    RowError(line, "Printing not found for this card", name, "printing_not_of_card")
                )
                continue
            printing_id = matches[0].id
        line_key = (card.id, value["section"], printing_id)
        deck.lines[line_key] = min(MAX_COPIES, deck.lines.get(line_key, 0) + quantity)

    name = "deck_allocations.csv"
    for line, value in _rows(
        name,
        files.get(name, ""),
        {"deck", "set_code", "collector_number", "finish", "language", "quantity"},
        report,
    ):
        deck = found.get(value["deck"])
        if deck is None:
            report.errors.append(
                RowError(
                    line,
                    f"Unknown deck {value['deck']!r}",
                    name,
                    "deck_unknown",
                    {"deck": value["deck"]},
                )
            )
            continue
        try:
            quantity = int(value["quantity"])
        except ValueError:
            quantity = 0
        if not 0 < quantity <= MAX_COPIES:
            report.errors.append(
                RowError(
                    line,
                    f"Invalid quantity {value['quantity']!r}",
                    name,
                    "invalid_quantity",
                    {"quantity": value["quantity"]},
                )
            )
            continue
        condition = (value.get("condition") or Condition.NM).upper()
        if condition not in Condition.__members__:
            report.errors.append(
                RowError(
                    line,
                    f"Unknown condition {condition!r}",
                    name,
                    "condition_unknown",
                    {"condition": condition},
                )
            )
            continue
        _, matches = await lookup.resolve(deck.game_id, value)
        if len(matches) != 1:
            problem = "No printing" if not matches else "Several printings"
            report.errors.append(
                RowError(
                    line,
                    f"{problem} for set {value['set_code']!r} number {value['collector_number']!r}",
                    name,
                )
            )
            continue
        if not any(card_id == matches[0].card_id for card_id, _, _ in deck.lines):
            report.errors.append(
                RowError(line, "This card is not in the deck", name, "card_not_in_deck")
            )
            continue
        deck.allocations.append(
            (line, matches[0], value["finish"], condition, value["language"], quantity)
        )
    return found


async def import_bundle(
    session: AsyncSession,
    user_id: int,
    files: dict[str, str],
    modules: list[str],
    set_mode: bool,
    dry_run: bool,
) -> BundleReport:
    """Import a bundle (`read_zip`): cards, then followed sets, then decks and their
    allocations. Everything is checked first; nothing is written if any row is invalid.

    `add` mode adds card quantities and deck lines; `set_mode` makes the collection's
    quantities equal to the file's and replaces the lines and allocations of decks of
    the same game and name. Followed sets take the file's language and finish."""
    report = BundleReport()
    for part in parts_of(files):
        module = PARTS[part]
        if module is not None and module not in modules:
            report.errors.append(
                RowError(
                    1,
                    f"The {module} module is not enabled",
                    FILES[part][0],
                    "module_disabled",
                    {"module": module},
                )
            )
    if report.errors:
        return report
    card_rows = []
    if "cards.csv" in files:
        cards_report = ImportReport()
        card_rows = await csv_io.parse_rows(session, files["cards.csv"], set_mode, cards_report)
        report.rows = cards_report.rows
        report.errors += [
            RowError(e.line, e.message, "cards.csv", e.code, e.params) for e in cards_report.errors
        ]
    follows = (
        await _parse_binder(session, files["binder_sets.csv"], report)
        if "binder_sets.csv" in files
        else []
    )
    deck_rows = await _parse_decks(session, files, report) if "decks" in parts_of(files) else {}
    if report.errors or dry_run:
        if not report.errors:
            report.counts = _counts(files, card_rows, follows, deck_rows)
        return report

    if card_rows:
        cards_report = ImportReport()
        if not await csv_io.apply_rows(session, user_id, card_rows, set_mode, cards_report):
            report.errors += [
                RowError(e.line, e.message, "cards.csv", e.code, e.params)
                for e in cards_report.errors
            ]
            return report
        report.imported = cards_report.imported
    for follow in follows:
        existing = await session.scalar(
            select(BinderSet).where(BinderSet.user_id == user_id, BinderSet.set_id == follow.set_id)
        )
        if existing is None:
            session.add(
                BinderSet(
                    user_id=user_id,
                    set_id=follow.set_id,
                    language=follow.language,
                    finish=follow.finish,
                )
            )
        else:
            existing.language, existing.finish = follow.language, follow.finish
    await session.flush()
    try:
        for row in deck_rows.values():
            await _write_deck(session, user_id, row, set_mode)
    except AllocationError as exc:
        await session.rollback()
        report.imported = 0
        line, message = exc.args if len(exc.args) == 2 else (1, str(exc))
        report.errors.append(RowError(line, message, "deck_allocations.csv"))
        return report
    report.counts = _counts(files, card_rows, follows, deck_rows)
    await session.commit()
    return report


def _counts(
    files: dict[str, str], card_rows: list, follows: list[_Follow], deck_rows: dict[str, _DeckRow]
) -> dict[str, int]:
    """Rows of each file of the bundle."""
    counts = {
        "cards.csv": len(card_rows),
        "binder_sets.csv": len(follows),
        "decks.csv": len(deck_rows),
        "deck_cards.csv": sum(len(d.lines) for d in deck_rows.values()),
        "deck_allocations.csv": sum(len(d.allocations) for d in deck_rows.values()),
    }
    return {name: n for name, n in counts.items() if name in files}


async def _write_deck(session: AsyncSession, user_id: int, row: _DeckRow, set_mode: bool) -> None:
    deck = await session.scalar(
        select(Deck)
        .where(Deck.user_id == user_id, Deck.game_id == row.game_id, Deck.name == row.name)
        .order_by(Deck.id)
        .limit(1)
        .with_for_update()
    )
    if deck is None:
        deck = Deck(user_id=user_id, game_id=row.game_id, name=row.name, format=row.format)
        session.add(deck)
        await session.flush()
        current: dict[tuple[int, str, int | None], int] = {}
    else:
        deck.format = row.format
        if set_mode:
            await session.execute(delete(DeckAllocation).where(DeckAllocation.deck_id == deck.id))
            await session.execute(delete(DeckCard).where(DeckCard.deck_id == deck.id))
            current = {}
        else:
            current = {
                (e.card_id, e.section, e.printing_id): e.quantity
                for e in await session.scalars(select(DeckCard).where(DeckCard.deck_id == deck.id))
            }
    for (card_id, section, printing_id), quantity in row.lines.items():
        total = min(MAX_COPIES, current.get((card_id, section, printing_id), 0) + quantity)
        await decks.set_line(session, deck, card_id, section, printing_id, total)
    await session.flush()
    for line, printing, finish, condition, language, quantity in row.allocations:
        item_id = await session.scalar(
            select(CollectionItem.id).where(
                CollectionItem.user_id == user_id,
                CollectionItem.printing_id == printing.id,
                CollectionItem.finish == finish,
                CollectionItem.condition == condition,
                CollectionItem.language == language,
            )
        )
        if item_id is None:
            raise AllocationError(line, "No copy of this card in the collection to allocate")
        try:
            await decks.allocate(session, deck, printing.card_id, quantity, item_id)
        except AllocationError as exc:
            raise AllocationError(line, str(exc)) from exc
    deck.updated_at = func.now()
