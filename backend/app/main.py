from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.dialects.postgresql import insert
from starlette.types import Scope

from app.api import admin, auth, catalog, collection, games, scan, users
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.games.base import registry
from app.models import Game


async def register_games() -> None:
    """Ensure every installed game provider has its `game` row."""
    async with get_sessionmaker()() as session:
        for provider in registry().values():
            stmt = insert(Game).values(id=provider.id, name=provider.name)
            await session.execute(
                stmt.on_conflict_do_update(index_elements=[Game.id], set_={"name": provider.name})
            )
        await session.commit()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if len(get_settings().secret_key) < 32:
        raise RuntimeError("Set TCG_SECRET_KEY to a random value of at least 32 characters")
    await register_games()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Fudabako", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    api = APIRouter(prefix="/api")
    api.include_router(auth.router)
    api.include_router(users.router)
    api.include_router(games.router)
    api.include_router(catalog.router)
    api.include_router(collection.router)
    api.include_router(scan.router)
    api.include_router(admin.router)

    @api.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api)
    mount_web(app, get_settings().web_dir)
    return app


def mount_web(app: FastAPI, web_dir: Path) -> None:
    """Serve the single-page web UI: static files, and index.html for client routes."""
    index = web_dir / "index.html"
    if not index.is_file():
        return
    root = web_dir.resolve()
    if (web_dir / "assets").is_dir():
        # File names are content hashed, so they can be cached forever.
        app.mount("/assets", ImmutableStaticFiles(directory=web_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        file = (root / path).resolve()
        if path and file.is_relative_to(root) and file.is_file():
            return FileResponse(file)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


class ImmutableStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


app = create_app()
