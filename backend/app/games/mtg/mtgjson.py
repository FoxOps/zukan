"""MTGJSON (https://mtgjson.com), second source of the MTG catalog.

Its CSV files (cards ~55 MB, identifiers ~16 MB, gzipped) are matched to Scryfall's
printings by set code and collector number. They fill missing Cardmarket and TCGplayer
product ids, rarities and artists, and are compared on card name, rarity, set name and
release date.
"""

import asyncio
import csv
import gzip
import logging
import sys
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from app.games.base import (
    CardData,
    CatalogIndex,
    Discrepancy,
    PrintingData,
    SecondaryBatch,
    compare,
)

log = logging.getLogger(__name__)

CSV_URL = "https://mtgjson.com/api/v5/csv"
BATCH_SIZE = 2000

# (set code, number, name, rarity, artist, uuid)
Row = tuple[str, str, str, str, str, str]


def _rows(path: Path, columns: tuple[str, ...]) -> list[tuple[str, ...]]:
    csv.field_size_limit(sys.maxsize)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as file:
        return [tuple(row.get(c) or "" for c in columns) for row in csv.DictReader(file)]


async def _download(http: httpx.AsyncClient, name: str, folder: Path) -> Path:
    path = folder / f"{name}.csv.gz"
    async with http.stream("GET", f"{CSV_URL}/{name}.csv.gz", headers={"Accept": "*/*"}) as r:
        r.raise_for_status()
        with path.open("wb") as file:
            async for chunk in r.aiter_bytes():
                file.write(chunk)
    return path


def check_sets(index: CatalogIndex, sets: list[tuple[str, ...]]) -> list[Discrepancy]:
    found = []
    for code, name, released in sets:
        ours = index.sets.get(code.lower())
        if ours is None:
            continue
        for field_name, primary, secondary in (
            ("set name", ours.name, name),
            ("release date", ours.release_date and ours.release_date.isoformat(), released),
        ):
            if (d := compare(ours.external_id, None, field_name, primary, secondary)) is not None:
                found.append(d)
    return found


def check_cards(
    index: CatalogIndex, rows: list[Row], ids: dict[str, tuple[str, str]]
) -> tuple[list[CardData], list[Discrepancy], int]:
    """Partial cards filling gaps, discrepancies and the number of matched printings."""
    cards: list[CardData] = []
    found: list[Discrepancy] = []
    matched = 0
    seen: set[tuple[str, str]] = set()
    for set_code, number, name, rarity, artist, uuid in rows:
        key = (set_code.lower(), number)
        stored = index.printings.get(key)
        if stored is None or key in seen:  # other faces of a printing come next
            continue
        seen.add(key)
        matched += 1
        # Front face names: the sources disagree on naming reversible cards "A // A".
        for field_name, primary, secondary in (
            ("name", stored.card_name.split(" // ")[0], name.split(" // ")[0]),
            ("rarity", stored.rarity, rarity),
        ):
            if (d := compare(key[0], number, field_name, primary, secondary)) is not None:
                found.append(d)
        cardmarket, tcgplayer = ids.get(uuid, ("", ""))
        markets = {
            source: int(value)
            for source, value in (("cardmarket", cardmarket), ("tcgplayer", tcgplayer))
            if value.isdigit() and source not in stored.market_ids
        }
        fills_gap = (not stored.rarity and rarity) or (not stored.artist and artist)
        if markets or fills_gap:
            cards.append(
                CardData(
                    external_id=stored.card_external_id,
                    name=stored.card_name,
                    partial=True,
                    printings=[
                        PrintingData(
                            external_id=stored.external_id,
                            set_external_id=stored.set_external_id,
                            rarity=rarity or None,
                            artist=artist or None,
                            attributes={"market_ids": markets} if markets else {},
                        )
                    ],
                )
            )
    return cards, found, matched


class MtgjsonSource:
    id = "mtgjson"
    name = "MTGJSON"

    async def fetch(
        self, http: httpx.AsyncClient, index: CatalogIndex
    ) -> AsyncIterator[SecondaryBatch]:
        with tempfile.TemporaryDirectory() as folder:
            files = {
                name: await _download(http, name, Path(folder))
                for name in ("sets", "cardIdentifiers", "cards")
            }
            # Parsing ~100k rows takes seconds: off the event loop.
            sets = await asyncio.to_thread(_rows, files["sets"], ("code", "name", "releaseDate"))
            identifiers = await asyncio.to_thread(
                _rows, files["cardIdentifiers"], ("uuid", "mcmId", "tcgplayerProductId")
            )
            rows = await asyncio.to_thread(
                _rows,
                files["cards"],
                ("setCode", "number", "name", "rarity", "artist", "uuid", "side"),
            )
        ids = {uuid: (mcm, tcg) for uuid, mcm, tcg in identifiers}
        # One row per face: keep the front ("a") or single-faced rows.
        cards_rows: list[Row] = [r[:6] for r in rows if r[6] in ("", "a")]  # type: ignore[misc]
        yield SecondaryBatch(discrepancies=check_sets(index, sets))
        cards, found, matched = await asyncio.to_thread(check_cards, index, cards_rows, ids)
        for start in range(0, max(len(cards), 1), BATCH_SIZE):
            yield SecondaryBatch(
                cards=cards[start : start + BATCH_SIZE],
                discrepancies=found if start == 0 else [],
                matched=matched if start == 0 else 0,
            )


source = MtgjsonSource()
