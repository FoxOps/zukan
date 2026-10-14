"""Pokémon TCG API data (pokemontcg.io), second source of the English Pokémon catalog.

The API itself is being replaced by a paid service and often fails; its data is also
published as JSON files on GitHub (one file per set, ~180 sets), read here. Sets are
matched to TCGdex's by official code (ptcgoCode), else by id ("sv1" = "sv01",
"sv3pt5" = "sv03.5"), else by name and release date; cards by number. It fills
missing English images, rarities and artists, and is compared on card name, rarity, set
name, release date and card count.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import httpx

from app.core.http import get_with_retry
from app.games.base import (
    CardData,
    CatalogIndex,
    Discrepancy,
    PrintingData,
    SecondaryBatch,
    SetData,
    StoredPrinting,
    compare,
)

log = logging.getLogger(__name__)

DATA_URL = "https://raw.githubusercontent.com/PokemonTCG/pokemon-tcg-data/master"
CONCURRENCY = 4


def _number(value: str) -> str:
    """ "001" and "1" are the same card; "TG05" and "tg5" too."""
    return re.sub(r"(?<![0-9])0+(?=[0-9])", "", value).casefold()


def _set_id(value: str) -> str:
    return _number(value.replace(".5", "pt5"))


def _release(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value.replace("/", "-")) if value else None
    except ValueError:
        return None


def match_sets(ours: dict[str, SetData], theirs: list[dict[str, Any]]) -> dict[str, str]:
    """Their set id -> our set external id (international sets only)."""
    candidates = [s for s in ours.values() if s.lang is None]
    by_code = {s.code.casefold(): s.external_id for s in candidates}
    by_id = {_set_id(s.external_id): s.external_id for s in candidates}
    by_name = {(s.name.casefold(), s.release_date): s.external_id for s in candidates}
    matches: dict[str, str] = {}
    used: set[str] = set()
    for raw in theirs:
        found = (
            by_id.get(_set_id(raw["id"]))
            or (raw.get("ptcgoCode") and by_code.get(raw["ptcgoCode"].casefold()))
            or by_name.get((raw["name"].casefold(), _release(raw.get("releaseDate"))))
        )
        if found and found not in used:
            matches[raw["id"]] = found
            used.add(found)
    return matches


def check_set(ours: SetData, raw: dict[str, Any]) -> list[Discrepancy]:
    released = _release(raw.get("releaseDate"))
    pairs = (
        ("set name", ours.name, raw.get("name")),
        ("release date", ours.release_date, released),
        ("card count", ours.total, raw.get("total")),
    )
    return [
        d
        for name, primary, secondary in pairs
        if (d := compare(ours.external_id, None, name, primary, secondary)) is not None
    ]


def check_cards(
    stored: dict[str, StoredPrinting], set_ext: str, cards: list[dict[str, Any]]
) -> SecondaryBatch:
    """`stored`: the set's printings by normalized number."""
    batch = SecondaryBatch()
    for raw in cards:
        printing = stored.get(_number(raw.get("number", "")))
        if printing is None:
            continue
        batch.matched += 1
        checks = (
            compare(set_ext, printing.external_id, "name", printing.card_name, raw.get("name")),
            # Rarity names differ between the two ("Holo Rare" / "Rare Holo").
            compare(
                set_ext, printing.external_id, "rarity", printing.rarity, raw.get("rarity"), True
            ),
        )
        batch.discrepancies += [d for d in checks if d is not None]
        image = (raw.get("images") or {}).get("large")
        images = {"en": image} if image and "en" not in printing.image_languages else {}
        gaps = (not printing.rarity and raw.get("rarity")) or (
            not printing.artist and raw.get("artist")
        )
        if images or gaps:
            batch.cards.append(
                CardData(
                    external_id=printing.card_external_id,
                    name=printing.card_name,
                    partial=True,
                    printings=[
                        PrintingData(
                            external_id=printing.external_id,
                            set_external_id=set_ext,
                            rarity=raw.get("rarity"),
                            artist=raw.get("artist"),
                            images=images,
                        )
                    ],
                )
            )
    return batch


class PokemonTcgSource:
    id = "pokemontcg"
    name = "Pokémon TCG API"

    async def fetch(
        self, http: httpx.AsyncClient, index: CatalogIndex
    ) -> AsyncIterator[SecondaryBatch]:
        theirs = (await get_with_retry(http, f"{DATA_URL}/sets/en.json")).json()
        matches = match_sets(index.sets, theirs)
        by_id = {raw["id"]: raw for raw in theirs}
        by_set: dict[str, dict[str, StoredPrinting]] = {}
        for (set_ext, _), printing in index.printings.items():
            by_set.setdefault(set_ext, {})[_number(printing.external_id)] = printing
        semaphore = asyncio.Semaphore(CONCURRENCY)

        async def one(set_id: str) -> SecondaryBatch:
            async with semaphore:
                try:
                    url = f"{DATA_URL}/cards/en/{set_id}.json"
                    cards = (await get_with_retry(http, url)).json()
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 404:
                        raise
                    cards = []
            set_ext = matches[set_id]
            batch = check_cards(by_set.get(set_ext, {}), set_ext, cards)
            batch.discrepancies += check_set(index.sets[set_ext], by_id[set_id])
            return batch

        log.info("pokemontcg: %s of %s sets matched", len(matches), len(theirs))
        for task in asyncio.as_completed([one(set_id) for set_id in matches]):
            yield await task


source = PokemonTcgSource()
