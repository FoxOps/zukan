import httpx
import respx

from app.core.config import get_settings
from app.core.http import get_limited, http_client
from tests.conftest import bearer, make_user


async def test_security_headers_on_every_answer(client, session):
    health = await client.get("/api/health")
    assert health.headers["x-frame-options"] == "DENY"
    assert health.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["referrer-policy"] == "same-origin"
    # A route's own policy keeps its rules and gets the framing one.
    await make_user(session)
    alice = await bearer(client, "alice")
    icon = await client.get("/api/games/lorcana/colors/amber/icon", headers=alice)
    assert icon.status_code == 200
    policy = icon.headers["content-security-policy"]
    assert policy.startswith("default-src 'none'") and policy.endswith("frame-ancestors 'none'")


async def test_large_bodies_refused_before_parsing(client, session, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_request_bytes", 1000)
    await make_user(session)
    alice = await bearer(client, "alice")
    big = b"game,set_code,collector_number,quantity\n" + b"x" * 2000
    response = await client.post(
        "/api/collection/import",
        files={"file": ("collection.csv", big, "text/csv")},
        headers=alice,
    )
    assert response.status_code == 413
    assert response.headers["x-frame-options"] == "DENY"

    # Streamed without a length: cut once the limit is passed.
    async def chunks():
        for _ in range(5):
            yield b"x" * 400

    streamed = await client.post(
        "/api/auth/login", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert streamed.status_code == 413
    # Small requests go through.
    assert (await client.get("/api/auth/me", headers=alice)).status_code == 200


async def test_downloads_stop_at_the_size_limit():
    with respx.mock() as router:
        router.get("https://img.example/big").respond(content=b"x" * 2000)
        router.get("https://img.example/small").respond(content=b"ok")
        router.get("https://img.example/missing").respond(404)
        async with http_client() as http:
            assert (await get_limited(http, "https://img.example/big", 1000))[1] is None
            assert (await get_limited(http, "https://img.example/small", 1000))[1] == b"ok"
            try:
                await get_limited(http, "https://img.example/missing", 1000)
            except httpx.HTTPStatusError as exc:
                assert exc.response.status_code == 404
            else:
                raise AssertionError("no error on 404")


async def test_text_answers_are_compressed_not_pictures(client):
    from app.core.middleware import _PICTURES

    response = await client.get("/api/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert _PICTURES.search("/api/printings/3/image")
    assert _PICTURES.search("/api/games/mtg/colors/W/icon")
    assert not _PICTURES.search("/api/cards")
