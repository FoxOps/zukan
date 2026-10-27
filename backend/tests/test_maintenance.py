from datetime import UTC, datetime

from app.models import JobKind, JobStatus, Role, SyncRun
from app.services import load
from tests.conftest import bearer, make_user

NOW = datetime(2026, 10, 27, tzinfo=UTC)


def test_monitor_enters_when_slow_during_catalog_refresh():
    monitor = load.LoadMonitor(limit_ms=500)
    # Slow without a catalog refresh: not our business.
    for _ in range(load.WINDOW * 2):
        monitor.record(2000, None, NOW)
    assert monitor.state is None
    # A few slow requests are not enough: the median of a full window decides.
    for latency in [2000] * 4 + [100] * (load.WINDOW - 4):
        monitor.record(latency, "mtg", NOW)
    assert monitor.state is None
    for _ in range(load.WINDOW):
        monitor.record(900, "mtg", NOW)
    assert monitor.state == load.Maintenance(since=NOW, game_id="mtg")


def test_monitor_leaves_after_calm_or_end_of_refresh():
    monitor = load.LoadMonitor(limit_ms=500)
    for _ in range(load.WINDOW):
        monitor.record(900, "mtg", NOW)
    # Fast samples must follow each other.
    for _ in range(load.CALM - 1):
        monitor.record(100, "mtg", NOW)
    monitor.record(900, "mtg", NOW)
    for _ in range(load.CALM - 1):
        monitor.record(100, "mtg", NOW)
    assert monitor.state is not None
    monitor.record(100, "mtg", NOW)
    assert monitor.state is None

    for _ in range(load.WINDOW):
        monitor.record(900, "mtg", NOW)
    assert monitor.state is not None
    monitor.record(900, None, NOW)
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
    latency, game_id = await load._sample(0)
    assert game_id is None and latency >= 0 and load._requests == []

    session.add(SyncRun(game_id="sorcery", kind=JobKind.catalog, status=JobStatus.running))
    await session.commit()
    load.record_request(5000)
    latency, game_id = await load._sample(0)
    assert game_id == "sorcery" and latency == 5000
