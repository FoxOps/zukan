import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import selectinload

from app.api import games
from app.api.deps import AdminUser, SessionDep
from app.core.budget import period_start
from app.core.config import get_settings
from app.core.http import http_client
from app.games.base import registry
from app.models import (
    ApiUsage,
    Card,
    CardSet,
    CatalogDiscrepancy,
    CatalogFieldRule,
    JobKind,
    JobStatus,
    JobTrigger,
    Printing,
    SyncRun,
)
from app.services import catalog, crosscheck, images, jobs, prices, refresh, schedule

router = APIRouter(prefix="/admin", tags=["admin"])


class JobOut(BaseModel):
    id: int
    game_id: str
    kind: JobKind
    status: JobStatus
    trigger: JobTrigger
    started_at: datetime
    finished_at: datetime | None
    report: dict[str, Any]
    error: str | None
    # Run time so far (running jobs) or total, from the server clock.
    elapsed_seconds: int


def _job_out(run: SyncRun, now: datetime) -> JobOut:
    end = run.finished_at or now
    elapsed = max(0, int((end - run.started_at).total_seconds()))
    fields = {name: getattr(run, name) for name in JobOut.model_fields if name != "elapsed_seconds"}
    return JobOut(**fields, elapsed_seconds=elapsed)


class ImageImportIn(BaseModel):
    # Folder name inside TCG_IMPORT_DIR.
    folder: str


class ImageImportOut(BaseModel):
    stored: int
    missing: int


def _check_game(game_id: str) -> None:
    if game_id not in registry():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown game {game_id!r}")


@router.get("/jobs")
async def list_jobs(
    _: AdminUser, session: SessionDep, game: str | None = None, limit: int = 50
) -> list[JobOut]:
    query = select(SyncRun).order_by(SyncRun.started_at.desc()).limit(min(limit, 500))
    if game:
        query = query.where(SyncRun.game_id == game)
    now = datetime.now(UTC)
    return [_job_out(run, now) for run in await session.scalars(query)]


class LastRunOut(BaseModel):
    kind: JobKind
    status: JobStatus
    started_at: datetime
    finished_at: datetime | None
    error: str | None


class GameStatusOut(BaseModel):
    game_id: str
    # Latest run of each job kind.
    runs: list[LastRunOut]


class QuotaOut(BaseModel):
    source: str
    period: Literal["day", "month"]
    used: int
    limit: int


class OverviewOut(BaseModel):
    games: list[GameStatusOut]
    quotas: list[QuotaOut]


def _quotas() -> list[tuple[str, Literal["day", "month"], int]]:
    """External APIs counted in `api_usage`, with their period and limit."""
    settings = get_settings()
    quotas: list[tuple[str, Literal["day", "month"], int]] = [
        ("apitcg", "month", settings.apitcg_monthly_requests),
        ("tcgapi_eu", "day", settings.tcgapi_eu_daily_requests),
    ]
    # Konami's database feeds the OCG game.
    if "yugioh-ocg" in registry():
        from app.games.yugioh.provider import YugiohSettings

        quotas.append(("konami", "day", YugiohSettings().konami_daily_requests))
    return quotas


@router.get("/overview")
async def overview(_: AdminUser, session: SessionDep) -> OverviewOut:
    """Data sync at a glance: latest run of each job per game, quotas used this period."""
    latest = (
        select(SyncRun)
        .ext(distinct_on(SyncRun.game_id, SyncRun.kind))
        .order_by(SyncRun.game_id, SyncRun.kind, SyncRun.started_at.desc())
    )
    runs: dict[str, list[LastRunOut]] = {game_id: [] for game_id in registry()}
    for run in await session.scalars(latest):
        if run.game_id in runs:
            runs[run.game_id].append(LastRunOut.model_validate(run, from_attributes=True))
    quotas = []
    for source, period, limit in _quotas():
        used = await session.scalar(
            select(ApiUsage.requests).where(
                ApiUsage.source == source, ApiUsage.period_start == period_start(period)
            )
        )
        quotas.append(QuotaOut(source=source, period=period, used=used or 0, limit=limit))
    return OverviewOut(
        games=[GameStatusOut(game_id=g, runs=r) for g, r in runs.items()], quotas=quotas
    )


class ScheduleOut(BaseModel):
    game_id: str
    kind: JobKind
    # When the worker starts it (at its first check from then on); now or earlier: at
    # its next check, within `check_seconds`.
    next_run_at: datetime
    check_seconds: int


@router.get("/schedule")
async def job_schedule(_: AdminUser) -> list[ScheduleOut]:
    """Next automatic run of every job the worker runs."""
    now = datetime.now(UTC)
    out = []
    for game_id in registry():
        for kind in schedule.jobs_for(game_id):
            at = await schedule.next_run(game_id, kind, now)
            if at is not None:
                out.append(
                    ScheduleOut(
                        game_id=game_id,
                        kind=kind,
                        next_run_at=at,
                        check_seconds=schedule.TICK_SECONDS,
                    )
                )
    return out


async def _complete_quietly(run_id: int, game_id: str, kind: JobKind) -> None:
    try:
        await jobs.complete_job(run_id, game_id, kind)
    except Exception:
        pass  # outcome is recorded on the sync_run row and logged


@router.post("/jobs/{game_id}/{kind}", status_code=status.HTTP_202_ACCEPTED)
async def start_job(
    game_id: str, kind: JobKind, _: AdminUser, background: BackgroundTasks
) -> dict[str, int]:
    _check_game(game_id)
    if kind == JobKind.prices and not prices.has_prices(registry()[game_id]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{game_id} has no price source")
    try:
        # Takes over a running auto run of the same job (waits for it to stop).
        run_id = await jobs.start_job(game_id, kind)
    except jobs.JobAlreadyRunning as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    background.add_task(_complete_quietly, run_id, game_id, kind)
    return {"run_id": run_id}


class ResetOut(BaseModel):
    printings: int
    cards: int
    sets: int
    # Printings kept because someone owns them.
    kept: int
    # Catalog job started to fill the catalog again.
    run_id: int


@router.post("/games/{game_id}/reset")
async def reset_catalog(
    game_id: str, _: AdminUser, session: SessionDep, background: BackgroundTasks
) -> ResetOut:
    """Delete the game's catalog except owned printings, then sync it again."""
    _check_game(game_id)
    await jobs.reap_runs()
    running = await session.scalar(
        select(SyncRun.kind).where(SyncRun.game_id == game_id, SyncRun.status == JobStatus.running)
    )
    if running is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A {running} job of {game_id} is running: wait for it"
        )
    report = await catalog.reset_catalog(session, game_id)
    games.clear_filter_values(game_id)
    run_id = await jobs.start_job(game_id, JobKind.catalog)
    background.add_task(_complete_quietly, run_id, game_id, JobKind.catalog)
    return ResetOut(
        printings=report.printings,
        cards=report.cards,
        sets=report.sets,
        kept=report.kept,
        run_id=run_id,
    )


@router.get("/import-folders")
async def list_import_folders(_: AdminUser) -> list[str]:
    root = get_settings().import_dir
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


@router.post("/images/{game_id}/import")
async def import_images(
    game_id: str, body: ImageImportIn, _: AdminUser, session: SessionDep
) -> ImageImportOut:
    _check_game(game_id)
    root = get_settings().import_dir.resolve()
    folder = (root / body.folder).resolve()
    if not folder.is_relative_to(root) or folder == root or not folder.is_dir():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown import folder")
    report = await images.import_image_folder(session, registry()[game_id], folder)
    return ImageImportOut(stored=report.stored, missing=report.missing)


class DiscrepancyOut(BaseModel):
    id: int
    game_id: str
    source: str
    set_code: str
    set_name: str
    # None: a set field.
    card_id: int | None
    card_name: str | None
    collector_number: str | None
    field: str
    primary_value: str | None
    secondary_value: str | None
    first_seen: datetime
    resolution: Literal["primary", "secondary", "custom"] | None
    resolved_value: str | None
    resolved_at: datetime | None
    by_rule: bool


class DiscrepancyCountOut(BaseModel):
    game_id: str
    source: str
    field: str
    # Open ones (not arbitrated yet), and arbitrated ones.
    count: int
    resolved: int = 0
    # Standing rule for this field, if any.
    rule: Literal["primary", "secondary"] | None = None
    rule_id: int | None = None


class DiscrepancyPageOut(BaseModel):
    items: list[DiscrepancyOut]
    total: int
    # Every discrepancy, counted per game, source and field.
    counts: list[DiscrepancyCountOut]


@router.get("/discrepancies")
async def list_discrepancies(
    _: AdminUser,
    session: SessionDep,
    game: str | None = None,
    source: str | None = None,
    field: str | None = None,
    state: Literal["open", "resolved", "all"] = "open",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DiscrepancyPageOut:
    """Where secondary catalog sources disagree with the primary one (kept unless
    arbitrated)."""
    query = (
        select(CatalogDiscrepancy, CardSet, Printing, Card)
        .join(CardSet, CatalogDiscrepancy.set_id == CardSet.id)
        .outerjoin(Printing, CatalogDiscrepancy.printing_id == Printing.id)
        .outerjoin(Card, Printing.card_id == Card.id)
    )
    if game:
        query = query.where(CatalogDiscrepancy.game_id == game)
    if source:
        query = query.where(CatalogDiscrepancy.source == source)
    if field:
        query = query.where(CatalogDiscrepancy.field == field)
    if state == "open":
        query = query.where(CatalogDiscrepancy.resolution.is_(None))
    elif state == "resolved":
        query = query.where(CatalogDiscrepancy.resolution.is_not(None))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.execute(
        query.order_by(CatalogDiscrepancy.game_id, CardSet.code, Printing.collector_number)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    counts = await session.execute(
        select(
            CatalogDiscrepancy.game_id,
            CatalogDiscrepancy.source,
            CatalogDiscrepancy.field,
            func.count().filter(CatalogDiscrepancy.resolution.is_(None)),
            func.count().filter(CatalogDiscrepancy.resolution.is_not(None)),
        )
        .group_by(CatalogDiscrepancy.game_id, CatalogDiscrepancy.source, CatalogDiscrepancy.field)
        .order_by(CatalogDiscrepancy.game_id, CatalogDiscrepancy.source, CatalogDiscrepancy.field)
    )
    rules = {
        (r.game_id, r.source, r.field): r for r in await session.scalars(select(CatalogFieldRule))
    }
    return DiscrepancyPageOut(
        items=[
            DiscrepancyOut(
                id=d.id,
                game_id=d.game_id,
                source=d.source,
                set_code=card_set.code,
                set_name=card_set.name,
                card_id=card.id if card else None,
                card_name=card.name if card else None,
                collector_number=printing.collector_number if printing else None,
                field=d.field,
                primary_value=d.primary_value,
                secondary_value=d.secondary_value,
                first_seen=d.first_seen,
                resolution=d.resolution,
                resolved_value=d.resolved_value,
                resolved_at=d.resolved_at,
                by_rule=d.by_rule,
            )
            for d, card_set, printing, card in rows
        ],
        total=total or 0,
        counts=[
            DiscrepancyCountOut(
                game_id=g,
                source=src,
                field=f,
                count=n,
                resolved=r,
                rule=rules[(g, src, f)].prefer if (g, src, f) in rules else None,
                rule_id=rules[(g, src, f)].id if (g, src, f) in rules else None,
            )
            for g, src, f, n, r in counts
        ],
    )


class ResolveIn(BaseModel):
    # None reopens the discrepancy (the primary's value comes back with the next sync).
    choice: Literal["primary", "secondary", "custom"] | None
    # The value to keep with "custom".
    value: Annotated[str | None, Field(max_length=500)] = None


@router.post("/discrepancies/{discrepancy_id}/resolve")
async def resolve_discrepancy(
    discrepancy_id: int, body: ResolveIn, admin: AdminUser, session: SessionDep
) -> dict[str, int]:
    """Arbitrate one discrepancy; the value chosen is written at once and kept after
    every later sync."""
    d = await session.get(CatalogDiscrepancy, discrepancy_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown discrepancy")
    if body.choice == "custom" and not (body.value or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A custom value is needed")
    if d.field not in crosscheck.SET_FIELDS | crosscheck.PRINTING_FIELDS and body.choice in (
        "secondary",
        "custom",
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{d.field!r} cannot be written")
    d.resolution = body.choice
    d.resolved_value = (body.value or "").strip()[:500] if body.choice == "custom" else None
    d.resolved_by = admin.id if body.choice else None
    d.resolved_at = datetime.now(UTC) if body.choice else None
    d.by_rule = False
    if body.choice is None and d.primary_value:
        # Back to the primary's value now, not only after the next sync.
        await crosscheck.write_value(session, d, d.primary_value)
    written = await crosscheck.apply_resolutions(session, d.game_id, [d.id])
    await session.commit()
    return {"written": written}


class RuleIn(BaseModel):
    game_id: str
    source: str
    field: str
    prefer: Literal["primary", "secondary"]


@router.put("/discrepancies/rules")
async def set_rule(body: RuleIn, admin: AdminUser, session: SessionDep) -> dict[str, int]:
    """Prefer one side for every discrepancy of this game, source and field, the open ones
    and those found later (single arbitrations of that field are replaced)."""
    _check_game(body.game_id)
    if body.prefer == "secondary" and body.field not in (
        crosscheck.SET_FIELDS | crosscheck.PRINTING_FIELDS
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{body.field!r} cannot be written")
    rule = await session.scalar(
        select(CatalogFieldRule).where(
            CatalogFieldRule.game_id == body.game_id,
            CatalogFieldRule.source == body.source,
            CatalogFieldRule.field == body.field,
        )
    )
    if rule is None:
        rule = CatalogFieldRule(
            game_id=body.game_id, source=body.source, field=body.field, created_by=admin.id
        )
        session.add(rule)
    rule.prefer = body.prefer
    await session.flush()
    await session.execute(
        update(CatalogDiscrepancy)
        .where(
            CatalogDiscrepancy.game_id == body.game_id,
            CatalogDiscrepancy.source == body.source,
            CatalogDiscrepancy.field == body.field,
        )
        .values(resolution=None, resolved_value=None, by_rule=False)
    )
    written = await crosscheck.apply_resolutions(session, body.game_id)
    await session.commit()
    return {"rule_id": rule.id, "written": written}


@router.delete("/discrepancies/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: int, _: AdminUser, session: SessionDep):
    """Remove a rule: the discrepancies it resolved are open again."""
    rule = await session.get(CatalogFieldRule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown rule")
    await session.execute(
        update(CatalogDiscrepancy)
        .where(
            CatalogDiscrepancy.game_id == rule.game_id,
            CatalogDiscrepancy.source == rule.source,
            CatalogDiscrepancy.field == rule.field,
            CatalogDiscrepancy.by_rule.is_(True),
        )
        .values(resolution=None, resolved_by=None, resolved_at=None, by_rule=False)
    )
    await session.delete(rule)
    await session.commit()


class StaleCardOut(BaseModel):
    id: int
    game_id: str
    name: str
    printing_count: int
    # Why it is stale: "not_seen" (missed by the last catalog sync), "no_image",
    # "no_attributes".
    reasons: list[str]
    last_seen_at: datetime | None
    refresh_attempted_at: datetime | None


class StalePageOut(BaseModel):
    items: list[StaleCardOut]
    total: int
    # Games whose provider can fetch single cards again.
    refreshable: list[str]


@router.get("/stale")
async def list_stale(
    _: AdminUser,
    session: SessionDep,
    game: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> StalePageOut:
    """Cards whose data is outdated or incomplete (see app.services.refresh)."""
    game_ids = [game] if game else list(registry())
    if game:
        _check_game(game)
    conditions = [await refresh.stale_condition(session, g) for g in game_ids]
    query = select(Card).where(or_(*conditions))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    cards = (
        await session.scalars(
            query.order_by(Card.game_id, Card.name, Card.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .options(selectinload(Card.printings))
        )
    ).all()
    reasons = await refresh.stale_reasons(session, cards)
    return StalePageOut(
        items=[
            StaleCardOut(
                id=c.id,
                game_id=c.game_id,
                name=c.name,
                printing_count=len(c.printings),
                reasons=reasons.get(c.id, []),
                last_seen_at=c.last_seen_at,
                refresh_attempted_at=c.refresh_attempted_at,
            )
            for c in cards
        ],
        total=total or 0,
        refreshable=[g for g in registry() if refresh.can_refresh(registry()[g])],
    )


class CardRefreshOut(BaseModel):
    updated: bool
    # Still stale after the refresh (the source does not have more).
    stale: bool


@router.post("/cards/{card_id}/refresh")
async def refresh_card(card_id: int, _: AdminUser, session: SessionDep) -> CardRefreshOut:
    """Fetch one card again from its game's source now."""
    card = await session.get(Card, card_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown card")
    provider = registry()[card.game_id]
    if not refresh.can_refresh(provider):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{card.game_id} cannot refresh cards")
    try:
        async with asyncio.timeout(60), http_client() as http:
            report = await refresh.refresh_cards(session, provider, http, [card_id])
    except TimeoutError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "The source took too long") from exc
    session.expire_all()
    card = await session.get(Card, card_id)
    return CardRefreshOut(
        updated=report.updated > 0, stale=card is not None and await refresh.is_stale(session, card)
    )
