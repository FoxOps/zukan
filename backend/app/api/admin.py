from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import AdminUser, SessionDep
from app.core.config import get_settings
from app.games.base import registry
from app.models import (
    Card,
    CardSet,
    CatalogDiscrepancy,
    JobKind,
    JobStatus,
    JobTrigger,
    Printing,
    SyncRun,
)
from app.services import images, jobs, prices

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
    return [JobOut.model_validate(r, from_attributes=True) for r in await session.scalars(query)]


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


class DiscrepancyCountOut(BaseModel):
    game_id: str
    source: str
    field: str
    count: int


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
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DiscrepancyPageOut:
    """Where secondary catalog sources disagree with the primary one (kept)."""
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
            func.count(),
        )
        .group_by(CatalogDiscrepancy.game_id, CatalogDiscrepancy.source, CatalogDiscrepancy.field)
        .order_by(CatalogDiscrepancy.game_id, CatalogDiscrepancy.source, CatalogDiscrepancy.field)
    )
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
            )
            for d, card_set, printing, card in rows
        ],
        total=total or 0,
        counts=[
            DiscrepancyCountOut(game_id=g, source=s, field=f, count=n) for g, s, f, n in counts
        ],
    )
