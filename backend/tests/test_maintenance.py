from datetime import UTC, datetime

import httpx

from app.core.config import get_settings
from app.main import create_app
from app.models import JobKind, JobStatus, Role, SyncRun
from app.services import load, maintenance_page
from tests.conftest import bearer, make_user

NOW = datetime(2026, 10, 27, tzinfo=UTC)


def test_monitor_enters_when_slow_during_catalog_refresh():
    monitor = load.LoadMonitor(limit_ms=500)
    # Slow without a catalog refresh (prices, images…): not our business.
    for _ in range(load.WINDOW * 2):
        monitor.record(2000, None, "mtg", NOW)
    assert monitor.state is None
    # A few slow requests are not enough: the median of a full window decides.
    for latency in [2000] * 4 + [100] * (load.WINDOW - 4):
        monitor.record(latency, "mtg", "mtg", NOW)
    assert monitor.state is None
    for _ in range(load.WINDOW):
        monitor.record(900, "mtg", "mtg", NOW)
    assert monitor.state == load.Maintenance(since=NOW, game_id="mtg")


def test_monitor_stays_until_the_data_sync_is_over():
    monitor = load.LoadMonitor(limit_ms=500)
    for _ in range(load.WINDOW):
        monitor.record(900, "mtg", "mtg", NOW)
    # Fast again in the middle of the refresh: still in maintenance.
    for _ in range(load.IDLE * 3):
        monitor.record(100, "mtg", "mtg", NOW)
    assert monitor.state is not None
    # The catalog job ends, the prices job and the next game follow: still in.
    monitor.record(100, None, "mtg", NOW)
    assert monitor.state == load.Maintenance(since=NOW, game_id="mtg")
    for _ in range(load.IDLE - 1):
        monitor.record(100, None, None, NOW)
    monitor.record(100, None, "pokemon", NOW)
    assert monitor.state == load.Maintenance(since=NOW, game_id="pokemon")
    # Nothing runs any more for IDLE samples in a row: over.
    for _ in range(load.IDLE - 1):
        monitor.record(100, None, None, NOW)
    assert monitor.state is not None
    monitor.record(100, None, None, NOW)
    assert monitor.state is None
    # A new refresh starts from an empty window.
    monitor.record(900, "mtg", "mtg", NOW)
    assert monitor.state is None


async def test_maintenance_blocks_users_not_admins(client, session, monkeypatch):
    await make_user(session, "root", role=Role.admin)
    await make_user(session)
    admin = await bearer(client, "root")
    user = await bearer(client, "alice")
    health = (await client.get("/api/health")).json()
    assert health["status"] == "ok" and health["maintenance"] is None

    monitor = load.LoadMonitor(limit_ms=500)
    monitor.state = load.Maintenance(since=NOW, game_id="mtg")
    monkeypatch.setattr(load, "_monitor", monitor)
    health = (await client.get("/api/health")).json()
    assert health["maintenance"]["game_id"] == "mtg"

    blocked = await client.get("/api/collection", headers=user)
    assert blocked.status_code == 503 and "maintenance" in blocked.json()["detail"]
    assert blocked.headers["retry-after"] == "60"
    # Clients still learn who is signed in.
    assert (await client.get("/api/auth/me", headers=user)).status_code == 200
    assert (await client.get("/api/collection", headers=admin)).status_code == 200
    assert (await client.get("/api/admin/jobs", headers=admin)).status_code == 200


async def test_sample_reports_running_catalog_and_requests(client, session, monkeypatch):
    from app.main import register_games

    await register_games()
    monkeypatch.setattr(load, "_monitor", load.LoadMonitor(limit_ms=500))
    monkeypatch.setattr(load, "_requests", [])
    await client.get("/api/games")
    await client.get("/api/health")  # not counted
    assert len(load._requests) == 1
    latency, activity = await load._sample(0)
    assert activity == load.Activity(None, None) and latency >= 0 and load._requests == []

    session.add(SyncRun(game_id="mtg", kind=JobKind.prices, status=JobStatus.running))
    session.add(SyncRun(game_id="pokemon", kind=JobKind.images, status=JobStatus.queued))
    await session.commit()
    latency, activity = await load._sample(0)
    assert activity == load.Activity(None, "mtg")

    session.add(SyncRun(game_id="sorcery", kind=JobKind.catalog, status=JobStatus.running))
    await session.commit()
    load.record_request(5000)
    latency, activity = await load._sample(0)
    assert activity == load.Activity("sorcery", "sorcery") and latency == 5000


async def test_maintenance_page_replaces_the_web_interface(tmp_path, session, monkeypatch):
    from app.main import register_games

    await register_games()
    web = tmp_path / "dist"
    web.mkdir()
    (web / "index.html").write_text("<html>app</html>")
    (web / "favicon.svg").write_text("<svg/>")
    monkeypatch.setattr(get_settings(), "web_dir", web)
    await make_user(session, "root", role=Role.admin)
    alice = await make_user(session)
    alice.language = "de"
    await session.commit()

    transport = httpx.ASGITransport(app=create_app())
    base = "http://testserver"
    async with (
        httpx.AsyncClient(transport=transport, base_url=base) as anonymous,
        httpx.AsyncClient(transport=transport, base_url=base) as user,
        httpx.AsyncClient(transport=transport, base_url=base) as admin,
    ):
        for client, name in ((user, "alice"), (admin, "root")):
            login = await client.post(
                "/api/auth/login",
                json={"username": name, "password": "password123", "mode": "cookie"},
                headers={"X-TCG-CSRF": "1"},
            )
            assert login.status_code == 200
        assert (await anonymous.get("/collection")).text == "<html>app</html>"

        monitor = load.LoadMonitor(limit_ms=500)
        monitor.state = load.Maintenance(since=NOW, game_id="mtg")
        monkeypatch.setattr(load, "_monitor", monitor)

        page = await anonymous.get("/collection", headers={"Accept-Language": "es-ES,fr;q=0.8"})
        assert page.status_code == 503 and page.headers["retry-after"] == "60"
        assert page.headers["cache-control"] == "no-store"
        assert '<html lang="es" data-known="0">' in page.text
        assert "Zukan se toma un descanso" in page.text
        assert 'src="data:image/webp;base64,' in page.text
        # The signed-in user's language wins over the browser's.
        page = await user.get("/", headers={"Accept-Language": "fr"})
        assert page.status_code == 503 and '<html lang="de" data-known="1">' in page.text
        # Administrators keep the interface; files stay served, the API stays JSON.
        assert (await admin.get("/admin/jobs")).text == "<html>app</html>"
        assert (await anonymous.get("/login")).text == "<html>app</html>"
        assert (await anonymous.get("/favicon.svg")).text == "<svg/>"
        assert (await anonymous.get("/api/health")).json()["maintenance"]["game_id"] == "mtg"
        blocked = await user.get("/api/collection", headers={"X-TCG-CSRF": "1"})
        assert blocked.status_code == 503 and "maintenance" in blocked.json()["detail"]


def test_maintenance_page_languages():
    assert maintenance_page.accept_language("de-CH, en;q=0.5") == "de"
    assert maintenance_page.accept_language("ja, fr;q=0.3, es;q=0.7") == "es"
    assert maintenance_page.accept_language("ja, fr;q=0") is None
    assert maintenance_page.accept_language(None) is None
    for lang, texts in maintenance_page.TEXTS.items():
        assert texts.keys() == maintenance_page.TEXTS["en"].keys()
        page = maintenance_page.render(lang, known=False)
        assert f'<html lang="{lang}"' in page and "$" not in page
    assert '<html lang="en"' in maintenance_page.render("ja", known=False)
