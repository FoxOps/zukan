from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import AdminUser, SessionDep
from app.core.config import get_settings
from app.games.base import registry
from app.models import JobKind, JobStatus, JobTrigger, SyncRun
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
