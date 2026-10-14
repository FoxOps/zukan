"""Store normalized catalog data from game providers (idempotent upserts)."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import delete, exists, func, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.progress import progress
from app.games.base import (
    CardData,
    CatalogBatch,
    GameProvider,
    PrintingData,
    SetData,
    catalog_version,
)
from app.models import Card, CardName, CardSet, Game, Printing
from app.services import prices


@dataclass
class SyncReport:
    sets: int = 0
    cards: int = 0
    printings: int = 0
    names: int = 0
    prices: int = 0
    pruned_prices: int = 0
    # Cards left without printings (a printing moved to another card).
    pruned_cards: int = 0
    catalog_version: int = 1


# Stay well under PostgreSQL's 32767 bind parameters per statement.
_CHUNK = 1000


def _chunks[T](rows: Sequence[T], size: int = _CHUNK) -> Iterable[Sequence[T]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _merge_unique(*lists: list[str]) -> list[str]:
    return list(dict.fromkeys(item for values in lists for item in values))


def _array_union(column: str) -> Any:
    """SQL merging the stored array with the incoming one, keeping first-seen order."""
    return literal_column(
        f"ARRAY(SELECT x FROM unnest(printing.{column} || excluded.{column}) "
        "WITH ORDINALITY AS t(x, n) GROUP BY x ORDER BY min(n))"
    )


@dataclass
class _Card:
    data: CardData
    printings: list[tuple[PrintingData, bool]]  # (printing, partial)


def _dedupe_cards(cards: list[CardData]) -> list[_Card]:
    """One upsert statement cannot touch the same row twice, so merge duplicates first.

    Full data wins over partial data for card fields; the merged card stays partial only
    when every source was partial."""
    merged: dict[str, _Card] = {}
    for card in cards:
        printings = [(p, card.partial if p.partial is None else p.partial) for p in card.printings]
        existing = merged.get(card.external_id)
        if existing is None:
            data = replace(card, colors=list(card.colors), names=dict(card.names), printings=[])
            merged[card.external_id] = _Card(data, printings)
            continue
        existing.printings.extend(printings)
        names = {**card.names, **existing.data.names}
        if existing.data.partial and not card.partial:
            existing.data = replace(card, colors=list(card.colors), printings=[])
            names = {**existing.data.names, **names}
        existing.data.names = names
    return list(merged.values())


def _merge_printing(first: PrintingData, second: PrintingData) -> PrintingData:
    """Merge two descriptions of one printing; `first` wins on conflicting fields."""
    return replace(
        first,
        collector_number=first.collector_number or second.collector_number,
        rarity=first.rarity or second.rarity,
        artist=first.artist or second.artist,
        finishes=_merge_unique(first.finishes, second.finishes),
        languages=_merge_unique(first.languages, second.languages),
        images={**second.images, **first.images},
        attributes={**second.attributes, **first.attributes},
        names={**second.names, **first.names},
    )


def _dedupe_printings(
    printings: list[tuple[PrintingData, bool]],
) -> list[tuple[PrintingData, bool]]:
    merged: dict[tuple[str, str], tuple[PrintingData, bool]] = {}
    for printing, partial in printings:
        key = (printing.set_external_id, printing.external_id)
        if key not in merged:
            merged[key] = (printing, partial)
            continue
        existing, existing_partial = merged[key]
        if existing_partial and not partial:
            merged[key] = (_merge_printing(printing, existing), False)
        else:
            merged[key] = (_merge_printing(existing, printing), existing_partial and partial)
    return list(merged.values())


# On conflict, full data replaces stored fields while partial data only fills gaps.
_PRINTING_FULL = {
    "card_id": "excluded.card_id",
    "collector_number": "excluded.collector_number",
    "rarity": "excluded.rarity",
    "artist": "excluded.artist",
    "image_urls": "printing.image_urls || excluded.image_urls",
    "attributes": "printing.attributes || excluded.attributes",
}
_PRINTING_PARTIAL = {
    "collector_number": "coalesce(printing.collector_number, excluded.collector_number)",
    "rarity": "coalesce(printing.rarity, excluded.rarity)",
    "artist": "coalesce(printing.artist, excluded.artist)",
    "image_urls": "excluded.image_urls || printing.image_urls",
    "attributes": "excluded.attributes || printing.attributes",
}


class CatalogWriter:
    def __init__(self, session: AsyncSession, game_id: str, price_source: str | None = None):
        self.session = session
        self.game_id = game_id
        self.price_source = price_source
        self.set_ids: dict[str, int] = {}
        self.report = SyncReport()

    async def load_sets(self) -> None:
        """Know the game's stored sets, for batches that only bring cards."""
        rows = await self.session.execute(
            select(CardSet.id, CardSet.external_id).where(CardSet.game_id == self.game_id)
        )
        self.set_ids |= {external_id: set_id for set_id, external_id in rows}

    async def write(self, batch: CatalogBatch) -> None:
        await self._upsert_sets(batch.sets)
        ids = await self._upsert_cards(_dedupe_cards(batch.cards))
        if batch.prices and self.price_source:
            # Prices refer to printings of the same batch.
            self.report.prices += await prices.store_quotes(
                self.session, self.price_source, batch.prices, prices.today(), ids
            )

    async def _upsert_sets(self, sets: list[SetData]) -> None:
        unique = list({s.external_id: s for s in sets}.values())
        for chunk in _chunks(unique):
            stmt = insert(CardSet).values(
                [
                    {
                        "game_id": self.game_id,
                        "external_id": s.external_id,
                        "code": s.code,
                        "name": s.name,
                        "lang": s.lang,
                        "release_date": s.release_date,
                        "total": s.total,
                        "icon_url": s.icon_url,
                    }
                    for s in chunk
                ]
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[CardSet.game_id, CardSet.external_id],
                set_={
                    col: stmt.excluded[col]
                    for col in ("code", "name", "lang", "release_date", "total", "icon_url")
                },
            ).returning(CardSet.id, CardSet.external_id)
            for set_id, external_id in await self.session.execute(stmt):
                self.set_ids[external_id] = set_id
        self.report.sets += len(unique)

    async def _upsert_card_rows(self, cards: list[CardData], partial: bool) -> dict[str, int]:
        ids: dict[str, int] = {}
        for chunk in _chunks(cards):
            stmt = insert(Card).values(
                [
                    {
                        "game_id": self.game_id,
                        "external_id": c.external_id,
                        "name": c.name,
                        "colors": c.colors,
                        "attributes": c.attributes,
                    }
                    for c in chunk
                ]
            )
            # Partial data only marks the card as seen; the update also makes RETURNING
            # yield ids of existing cards.
            set_ = {"last_seen_at": func.now()}
            if not partial:
                set_ |= {col: stmt.excluded[col] for col in ("name", "colors", "attributes")}
            stmt = stmt.on_conflict_do_update(
                index_elements=[Card.game_id, Card.external_id], set_=set_
            ).returning(Card.id, Card.external_id)
            ids.update({ext: cid for cid, ext in await self.session.execute(stmt)})
        return ids

    async def _upsert_cards(self, cards: list[_Card]) -> prices.PrintingIds:
        """Store cards and their printings, return printing ids by external ids."""
        full = [c.data for c in cards if not c.data.partial]
        partial = [c.data for c in cards if c.data.partial]
        card_ids = await self._upsert_card_rows(full, partial=False)
        card_ids |= await self._upsert_card_rows(partial, partial=True)
        self.report.cards += len(cards)

        names: list[dict[str, Any]] = []
        stored: prices.PrintingIds = {}
        printing_rows: list[tuple[int, PrintingData, bool]] = []
        for card in cards:
            card_id = card_ids[card.data.external_id]
            names += [
                {"card_id": card_id, "printing_id": None, "lang": lang, "name": name}
                for lang, name in card.data.names.items()
            ]
            for printing, partial in _dedupe_printings(card.printings):
                printing_rows.append((card_id, printing, partial))

        printing_ids = await self._upsert_printings(
            [(cid, p) for cid, p, partial in printing_rows if not partial], _PRINTING_FULL
        )
        printing_ids |= await self._upsert_printings(
            [(cid, p) for cid, p, partial in printing_rows if partial], _PRINTING_PARTIAL
        )
        self.report.printings += len(printing_rows)
        for card_id, printing, _ in printing_rows:
            printing_id = printing_ids[
                (self.set_ids[printing.set_external_id], printing.external_id)
            ]
            stored[(printing.set_external_id, printing.external_id)] = printing_id
            names += [
                {"card_id": card_id, "printing_id": printing_id, "lang": lang, "name": name}
                for lang, name in printing.names.items()
            ]
        await self._insert_names(names)
        return stored

    async def _upsert_printings(
        self, rows: list[tuple[int, PrintingData]], on_conflict: dict[str, str]
    ) -> dict[tuple[int, str], int]:
        ids: dict[tuple[int, str], int] = {}
        for chunk in _chunks(rows):
            values = []
            for card_id, p in chunk:
                if p.set_external_id not in self.set_ids:
                    raise ValueError(
                        f"Printing {p.external_id} references unknown set {p.set_external_id!r}"
                    )
                values.append(
                    {
                        "card_id": card_id,
                        "set_id": self.set_ids[p.set_external_id],
                        "external_id": p.external_id,
                        "collector_number": p.collector_number,
                        "rarity": p.rarity,
                        "artist": p.artist,
                        "finishes": p.finishes,
                        "languages": p.languages,
                        "image_urls": p.images,
                        "attributes": p.attributes,
                    }
                )
            stmt = insert(Printing).values(values)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Printing.set_id, Printing.external_id],
                set_={
                    "finishes": _array_union("finishes"),
                    "languages": _array_union("languages"),
                    "last_seen_at": func.now(),
                    **{col: literal_column(sql) for col, sql in on_conflict.items()},
                },
            ).returning(Printing.id, Printing.set_id, Printing.external_id)
            ids.update(
                {(set_id, ext): pid for pid, set_id, ext in await self.session.execute(stmt)}
            )
        return ids

    async def _insert_names(self, names: list[dict[str, Any]]) -> None:
        for chunk in _chunks(names):
            await self.session.execute(insert(CardName).values(chunk).on_conflict_do_nothing())
        self.report.names += len(names)


async def sync_catalog(
    session: AsyncSession, provider: GameProvider, http: httpx.AsyncClient
) -> SyncReport:
    """Fetch and store the provider catalog, committing after each batch."""
    writer = CatalogWriter(session, provider.id, provider.price_source)
    async for batch in provider.fetch_catalog(http):
        await writer.write(batch)
        await session.commit()
        await progress()
    if provider.price_source and writer.report.prices:
        writer.report.pruned_prices = await prices.prune_history(
            session, provider.id, provider.price_source
        )
    pruned = await session.execute(
        delete(Card).where(
            Card.game_id == provider.id, ~exists().where(Printing.card_id == Card.id)
        )
    )
    writer.report.pruned_cards = pruned.rowcount
    writer.report.catalog_version = catalog_version(provider)
    await session.execute(
        update(Game).where(Game.id == provider.id).values(last_catalog_sync=datetime.now(UTC))
    )
    await session.commit()
    return writer.report
