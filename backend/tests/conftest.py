import os
import socket

os.environ.setdefault("TCG_DATABASE_URL", "postgresql+asyncpg://tcg:tcg@localhost:5432/tcg_test")
os.environ["TCG_COOKIE_SECURE"] = "false"
os.environ["TCG_PUBLIC_URL"] = "http://testserver"
os.environ["TCG_SECRET_KEY"] = "test-secret-key-with-enough-length-for-hs256"
# Tests needing the web UI build their own.
os.environ["TCG_WEB_DIR"] = "/nonexistent"

import json  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402
from pathlib import Path  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
import respx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core import oidc  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.db import get_engine, get_sessionmaker  # noqa: E402
from app.core.http import http_client  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.games.base import get_provider  # noqa: E402
from app.games.sorcery.provider import API_URL as SORCERY_URL  # noqa: E402
from app.games.sorcery.provider import CARDMARKET_URL  # noqa: E402
from app.main import create_app, register_games  # noqa: E402
from app.models import Base, Role, User  # noqa: E402
from app.services.catalog import sync_catalog  # noqa: E402

CSRF = {"X-TCG-CSRF": "1"}
SORCERY_CARDS = json.loads((Path(__file__).parent / "fixtures" / "sorcery_cards.json").read_text())


@pytest.fixture(scope="session", autouse=True)
async def database() -> AsyncIterator[None]:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean_tables() -> AsyncIterator[None]:
    yield
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver", "db"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch) -> None:
    """Fail fast on real HTTP calls: every external API must be mocked with respx."""
    real = socket.getaddrinfo

    def guarded(host, *args, **kwargs):
        if host not in _LOCAL_HOSTS:
            raise OSError(f"Network access to {host} in tests (mock it with respx)")
        return real(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded)


@pytest.fixture(autouse=True)
def reset_auth_config() -> None:
    settings = get_settings()
    settings.oidc_providers = []
    settings.local_login_enabled = True
    oidc.get_auth_config.cache_clear()
    oidc._clients.clear()


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as s:
        yield s


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    await register_games()
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def make_user(
    session: AsyncSession,
    username: str = "alice",
    password: str | None = "password123",
    role: Role = Role.user,
    disabled: bool = False,
) -> User:
    user = User(
        username=username,
        password_hash=hash_password(password) if password else None,
        role=role,
        disabled=disabled,
    )
    session.add(user)
    await session.commit()
    return user


async def bearer(client: httpx.AsyncClient, username: str, password: str = "password123") -> dict:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def sorcery_router():
    with respx.mock(assert_all_called=False) as router:
        # No Cardmarket prices unless a test mocks them (test_sorcery_price_job).
        router.get(url__startswith=CARDMARKET_URL, name="cardmarket").respond(404)
        router.get(SORCERY_URL, name="sorcery").respond(json=SORCERY_CARDS)
        yield router


@pytest.fixture
def sorcery_api(sorcery_router):
    return sorcery_router["sorcery"]


async def sync_sorcery(session: AsyncSession):
    async with http_client() as http:
        return await sync_catalog(session, get_provider("sorcery"), http)
