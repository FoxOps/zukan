"""Secondary catalog sources: fill gaps left by the primary source and record where they
disagree (`catalog_discrepancy`, shown to administrators). The primary's values are kept
unless an administrator chose otherwise (`apply_resolutions`).
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import httpx
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.progress import progress
from app.games.base import (
    CatalogIndex,
    CatalogSource,
    Discrepancy,
    GameProvider,
    SetData,
    StoredPrinting,
)
from app.models import (
    Card,
    CardName,
    CardSet,
    CatalogDiscrepancy,
    CatalogFieldRule,
    Printing,
)
from app.services.catalog import CatalogWriter

log = logging.getLogger(__name__)


@dataclass
class CrossCheckReport:
    # Stored printings found in secondary sources.
    matched: int = 0
    discrepancies: int = 0
    # Secondary sources that failed (the catalog sync itself still succeeds).
    failed_sources: list[str] = field(default_factory=list)
    # Values chosen by administrators written over the primary's.
    resolved: int = 0


def secondary_sources(provider: GameProvider) -> list[CatalogSource]:
    return list(getattr(provider, "secondary_sources", []))


async def build_index(session: AsyncSession, game_id: str) -> CatalogIndex:
    sets = {
        s.external_id: SetData(
            external_id=s.external_id,
            code=s.code,
            name=s.name,
            lang=s.lang,
            release_date=s.release_date,
            total=s.total,
        )
        for s in await session.scalars(select(CardSet).where(CardSet.game_id == game_id))
    }
    rows = await session.execute(
        select(Printing, CardSet.external_id, Card.external_id, Card.name)
        .join(CardSet, Printing.set_id == CardSet.id)
        .join(Card, Printing.card_id == Card.id)
        .where(CardSet.game_id == game_id)
    )
    printings = {
        (set_ext, p.external_id): StoredPrinting(
            set_external_id=set_ext,
            external_id=p.external_id,
            collector_number=p.collector_number,
            rarity=p.rarity,
            artist=p.artist,
            card_external_id=card_ext,
            card_name=card_name,
            image_languages=tuple(p.image_urls),
            market_ids=dict(p.attributes.get("market_ids") or {}),
            languages=tuple(p.languages),
        )
        for p, set_ext, card_ext, card_name in rows
    }
    return CatalogIndex(sets=sets, printings=printings)


async def _store_discrepancies(
    session: AsyncSession,
    game_id: str,
    source: str,
    found: list[Discrepancy],
    started: datetime,
) -> int:
    set_ids = dict(
        (await session.execute(
            select(CardSet.external_id, CardSet.id).where(CardSet.game_id == game_id)
        )).all()
    )  # fmt: skip
    rows = []
    printing_keys = {(d.set_external_id, d.printing_external_id) for d in found}
    printing_ids: dict[tuple[str, str], int] = {}
    if any(ext for _, ext in printing_keys):
        result = await session.execute(
            select(CardSet.external_id, Printing.external_id, Printing.id)
            .join(CardSet, Printing.set_id == CardSet.id)
            .where(CardSet.game_id == game_id)
        )
        printing_ids = {(s, p): pid for s, p, pid in result}
    for d in found:
        set_id = set_ids.get(d.set_external_id)
        printing_id = (
            printing_ids.get((d.set_external_id, d.printing_external_id))
            if d.printing_external_id
            else None
        )
        if set_id is None or (d.printing_external_id and printing_id is None):
            continue
        rows.append(
            {
                "game_id": game_id,
                "source": source,
                "set_id": set_id,
                "printing_id": printing_id,
                "field": d.field,
                "primary_value": (d.primary or "")[:500],
                "secondary_value": (d.secondary or "")[:500],
            }
        )
    unique = list({(r["set_id"], r["printing_id"], r["field"]): r for r in rows}.values())
    for start in range(0, len(unique), 1000):
        stmt = insert(CatalogDiscrepancy).values(unique[start : start + 1000])
        stmt = stmt.on_conflict_do_update(
            index_elements=["source", "set_id", "printing_id", "field"],
            set_={
                "primary_value": stmt.excluded.primary_value,
                "secondary_value": stmt.excluded.secondary_value,
                "last_seen": datetime.now(UTC),
            },
        )
        await session.execute(stmt)
    # Disagreements this run did not find again are solved.
    await session.execute(
        delete(CatalogDiscrepancy).where(
            CatalogDiscrepancy.game_id == game_id,
            CatalogDiscrepancy.source == source,
            CatalogDiscrepancy.last_seen < started,
        )
    )
    return len(unique)


# Fields an arbitration can write: set fields (no printing) and printing fields.
SET_FIELDS = {"set name", "release date", "card count"}
PRINTING_FIELDS = {"name", "rarity"}


def chosen_value(d: CatalogDiscrepancy) -> str | None:
    """Value to write for a resolved discrepancy (None: keep the primary's)."""
    if d.resolution == "secondary":
        return d.secondary_value
    if d.resolution == "custom":
        return d.resolved_value
    return None


async def write_value(session: AsyncSession, d: CatalogDiscrepancy, value: str) -> None:
    if d.printing_id is None:
        if d.field == "set name":
            await session.execute(update(CardSet).where(CardSet.id == d.set_id).values(name=value))
        elif d.field == "release date":
            day = date.fromisoformat(value[:10])
            await session.execute(
                update(CardSet).where(CardSet.id == d.set_id).values(release_date=day)
            )
        elif d.field == "card count" and value.isdigit():
            await session.execute(
                update(CardSet).where(CardSet.id == d.set_id).values(total=int(value))
            )
        return
    printing = await session.get(Printing, d.printing_id)
    if printing is None:
        return
    if d.field == "rarity":
        printing.rarity = value
    elif d.field == "name":
        card = await session.get(Card, printing.card_id)
        if card is None:
            return
        card.name = value
        # The English name shown and searched: the chosen one instead of the primary's.
        await session.execute(
            delete(CardName).where(
                CardName.card_id == card.id,
                CardName.printing_id.is_(None),
                CardName.lang == "en",
                CardName.name == d.primary_value,
            )
        )
        await session.execute(
            insert(CardName)
            .values(card_id=card.id, printing_id=None, lang="en", name=value)
            .on_conflict_do_nothing()
        )


async def apply_resolutions(
    session: AsyncSession, game_id: str, ids: Iterable[int] | None = None
) -> int:
    """Resolve open discrepancies covered by field rules, then write the values chosen by
    administrators over the primary's. Returns the number of values written."""
    rules = (
        await session.scalars(select(CatalogFieldRule).where(CatalogFieldRule.game_id == game_id))
    ).all()
    for rule in rules:
        await session.execute(
            update(CatalogDiscrepancy)
            .where(
                CatalogDiscrepancy.game_id == game_id,
                CatalogDiscrepancy.source == rule.source,
                CatalogDiscrepancy.field == rule.field,
                CatalogDiscrepancy.resolution.is_(None),
            )
            .values(
                resolution=rule.prefer,
                resolved_by=rule.created_by,
                resolved_at=datetime.now(UTC),
                by_rule=True,
            )
        )
    query = select(CatalogDiscrepancy).where(
        CatalogDiscrepancy.game_id == game_id,
        CatalogDiscrepancy.resolution.in_(["secondary", "custom"]),
    )
    if ids is not None:
        query = query.where(CatalogDiscrepancy.id.in_(list(ids)))
    written = 0
    for d in await session.scalars(query):
        value = chosen_value(d)
        if value:
            await write_value(session, d, value)
            written += 1
    return written


async def cross_check(
    session: AsyncSession, provider: GameProvider, http: httpx.AsyncClient
) -> CrossCheckReport:
    """Run the provider's secondary sources against what the primary stored."""
    report = CrossCheckReport()
    sources = secondary_sources(provider)
    if not sources:
        return report
    index = await build_index(session, provider.id)
    for source in sources:
        started = datetime.now(UTC)
        writer = CatalogWriter(session, provider.id, mark_seen=False)
        await writer.load_sets()
        found: list[Discrepancy] = []
        matched = 0
        try:
            async for batch in source.fetch(http, index):
                if batch.cards:
                    await writer.write_cards(batch.cards)
                    await session.commit()
                found += batch.discrepancies
                matched += batch.matched
                await progress()
        except Exception:
            # The primary catalog is stored already: a failing check does not undo it.
            await session.rollback()
            log.exception("Secondary source %s of %s failed", source.id, provider.id)
            report.failed_sources.append(source.id)
            continue
        report.matched += matched
        report.discrepancies += await _store_discrepancies(
            session, provider.id, source.id, found, started
        )
        await session.commit()
        log.info("%s: %s printings cross-checked, %s discrepancies", source.id, matched, len(found))
    report.resolved = await apply_resolutions(session, provider.id)
    await session.commit()
    return report
