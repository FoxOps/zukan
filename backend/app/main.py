import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import insert
from starlette.types import Scope

from app import __version__
from app.api import admin, auth, catalog, collection, games, releases, scan, users
from app.api.schemas import HealthOut, MaintenanceOut
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.http import close_shared_http_client
from app.core.middleware import BodyLimit, RequestTimer, SecurityHeaders, TextCompression
from app.core.security import hash_password
from app.games.base import registry, shipped_folders
from app.models import Game, Role, User
from app.services import layout, load
from app.services.jobs import reap_runs
from app.services.symbols import ensure_symbols

logger = logging.getLogger(__name__)


async def register_games() -> None:
    """Ensure every installed game provider has its `game` row."""
    async with get_sessionmaker()() as session:
        for provider in registry().values():
            stmt = insert(Game).values(id=provider.id, name=provider.name)
            await session.execute(
                stmt.on_conflict_do_update(index_elements=[Game.id], set_={"name": provider.name})
            )
        await session.commit()


async def create_default_admin() -> None:
    """First start: create the default administrator so somebody can sign in."""
    settings = get_settings()
    if not settings.default_admin_password:
        return
    async with get_sessionmaker()() as session:
        if await session.scalar(select(exists().select_from(User))):
            return
        session.add(
            User(
                username=settings.default_admin_username,
                role=Role.admin,
                password_hash=hash_password(settings.default_admin_password),
            )
        )
        await session.commit()
    logger.warning(
        "Created default administrator %r: sign in and change its password",
        settings.default_admin_username,
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if len(get_settings().secret_key) < 32:
        raise RuntimeError("Set TCG_SECRET_KEY to a random value of at least 32 characters")
    await register_games()
    await create_default_admin()
    # Jobs this API process ran before a restart are gone.
    await reap_runs()
    # Reference copy of the shipped pictures, next to the user's own.
    try:
        layout.install_defaults(get_settings().image_dir, shipped_folders())
    except OSError as exc:
        logger.warning("Shipped pictures not copied to the image folder: %s", exc)
    # Game symbols are downloaded once; the API serves requests meanwhile.
    symbols = asyncio.create_task(ensure_symbols())
    # Maintenance mode while a catalog refresh slows the server down.
    watcher = asyncio.create_task(load.watch())
    yield
    symbols.cancel()
    watcher.cancel()
    await close_shared_http_client()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Zukan",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    api = APIRouter(prefix="/api")
    api.include_router(auth.router)
    api.include_router(users.router)
    api.include_router(games.router)
    api.include_router(catalog.router)
    api.include_router(collection.router)
    api.include_router(scan.router)
    api.include_router(admin.router)
    api.include_router(releases.router)

    @api.get("/health", tags=["meta"])
    async def health() -> HealthOut:
        state = load.maintenance()
        return HealthOut(
            version=__version__,
            maintenance=MaintenanceOut(since=state.since, game_id=state.game_id) if state else None,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Same shape as other errors, so clients show their own message; details only in
        # the server log.
        logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    app.include_router(api)
    mount_web(app, get_settings().web_dir)
    # Last added runs first: headers on every answer, the 413 included.
    app.add_middleware(TextCompression)
    app.add_middleware(RequestTimer)
    app.add_middleware(BodyLimit)
    app.add_middleware(SecurityHeaders)
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
