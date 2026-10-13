import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.games.sorcery.provider import parse_cards
from app.models import Card, CardName, CardSet, JobKind, JobStatus, Printing, Role, SyncRun
from app.services import jobs
from app.worker import is_due
from tests.conftest import SORCERY_CARDS as FIXTURE
from tests.conftest import bearer, make_user, sync_sorcery

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(autouse=True)
def dirs(tmp_path):
    settings = get_settings()
    settings.image_dir = tmp_path / "images"
    settings.import_dir = tmp_path / "import"
    settings.import_dir.mkdir()
    yield


async def count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


def by_id(batch, external_id):
    return next(c for c in batch.cards if c.external_id == external_id)


def test_parse_groups_finishes_per_set_and_product():
    batch = parse_cards(FIXTURE)
    assert {s.external_id: s.name for s in batch.sets} == {
        "001": "Alpha",
        "002": "Beta",
        "004": "Arthurian Legends",
        "999": "Promo",
    }

    abundance = by_id(batch, "abundance")
    assert abundance.colors == ["water"]
    assert sorted(
        (p.set_external_id, p.external_id, tuple(p.finishes)) for p in abundance.printings
    ) == [
        ("001", "abundance-b", ("standard", "foil")),
        ("002", "abundance-b", ("standard", "foil")),
    ]
    printing = abundance.printings[0]
    assert printing.attributes["slugs"] == {
        "standard": f"{printing.set_external_id}-abundance-b-s",
        "foil": f"{printing.set_external_id}-abundance-b-f",
    }

    assert by_id(batch, "aqueduct").colors == ["earth", "water"]
    assert by_id(batch, "13_treasures_of_britain").colors == []

    archimago = {p.external_id: p.finishes for p in by_id(batch, "archimago").printings}
    assert archimago["archimago-op"] == ["rainbow"]

    # Same set, different products stay separate printings.
    avatar = {
        p.external_id: p.finishes
        for p in by_id(batch, "avatar_of_air").printings
        if p.set_external_id == "001"
    }
    assert avatar == {"avatar_of_air-pd": ["standard"], "avatar_of_air-b": ["foil"]}

    druid = by_id(batch, "druid")
    assert druid.attributes["back"] is not None


@pytest.mark.smoke
async def test_sync_is_idempotent(session, sorcery_api):
    from app.main import register_games

    await register_games()
    report = await sync_sorcery(session)
    assert report.cards == 7
    counts = [await count(session, m) for m in (CardSet, Card, Printing, CardName)]
    assert counts[:3] == [4, 7, report.printings]

    await sync_sorcery(session)
    assert [await count(session, m) for m in (CardSet, Card, Printing, CardName)] == counts


async def test_sync_merges_new_finishes(session, sorcery_api):
    from app.main import register_games

    await register_games()
    await sync_sorcery(session)
    changed = json.loads(json.dumps(FIXTURE))
    abundance = next(c for c in changed if c["slug"] == "abundance")
    extra = json.loads(json.dumps(abundance["printings"][0]))
    extra["slug"] = extra["slug"][:-1] + "rf"
    extra["meta"]["finish"] = "Rainbow"
    abundance["printings"].append(extra)
    sorcery_api.respond(json=changed)
    await sync_sorcery(session)

    session.expire_all()
    printing = await session.scalar(
        select(Printing)
        .join(CardSet)
        .where(Printing.external_id == "abundance-b", CardSet.code == extra["set"]["code"])
    )
    assert printing.finishes == ["standard", "foil", "rainbow"]
    assert printing.attributes["slugs"]["rainbow"] == extra["slug"]


@pytest.fixture
async def synced(session, sorcery_api):
    from app.main import register_games

    await register_games()
    await sync_sorcery(session)


@pytest.mark.smoke
async def test_search_and_card_detail(client, session, synced):
    await make_user(session)
    headers = await bearer(client, "alice")

    # Exact match first, then prefix, then substring matches.
    ranked = (await client.get("/api/cards", params={"q": "a"}, headers=headers)).json()
    names = [c["name"] for c in ranked["items"]]
    assert names[0] == "Abundance" and names[-1] == "13 Treasures of Britain"
    page = (await client.get("/api/cards", params={"q": "abun"}, headers=headers)).json()
    assert [c["name"] for c in page["items"]] == ["Abundance"]
    assert page["items"][0]["printing_count"] == 2

    water = (
        await client.get(
            "/api/cards", params={"game": "sorcery", "color": ["water"]}, headers=headers
        )
    ).json()
    assert {c["name"] for c in water["items"]} == {"Abundance", "Aqueduct"}
    both = (
        await client.get("/api/cards", params={"color": ["earth", "water"]}, headers=headers)
    ).json()
    assert [c["name"] for c in both["items"]] == ["Aqueduct"]

    sets = (await client.get("/api/games/sorcery/sets", headers=headers)).json()
    promo = next(s for s in sets if s["code"] == "999")
    in_promo = (
        await client.get("/api/cards", params={"set_id": promo["id"]}, headers=headers)
    ).json()
    assert in_promo["total"] == 4

    paged = (
        await client.get("/api/cards", params={"page_size": 3, "page": 3}, headers=headers)
    ).json()
    assert paged["total"] == 7 and len(paged["items"]) == 1

    card_id = page["items"][0]["id"]
    card = (await client.get(f"/api/cards/{card_id}", headers=headers)).json()
    assert [p["set"]["code"] for p in card["printings"]] == ["002", "001"]
    assert card["printings"][0]["names"] == {"en": "Abundance"}
    assert card["printings"][0]["image"] is None
    assert card["attributes"]["thresholds"]["water"] >= 1
    assert (await client.get("/api/cards/999999", headers=headers)).status_code == 404


async def test_image_import_and_serving(client, session, synced):
    await make_user(session, "root", role=Role.admin)
    headers = await bearer(client, "root")
    folder = get_settings().import_dir / "sorcery-drive" / "nested"
    folder.mkdir(parents=True)
    (folder / "001-abundance-b-s.png").write_bytes(PNG)
    (folder / "002-abundance-b-f.png").write_bytes(PNG)  # only foil scan available
    (folder / "notes.txt").write_text("ignored")

    assert (await client.get("/api/admin/import-folders", headers=headers)).json() == [
        "sorcery-drive"
    ]
    for bad in ["..", "../..", "/etc", "missing", ""]:
        response = await client.post(
            "/api/admin/images/sorcery/import", json={"folder": bad}, headers=headers
        )
        assert response.status_code == 400, bad

    response = await client.post(
        "/api/admin/images/sorcery/import", json={"folder": "sorcery-drive"}, headers=headers
    )
    assert response.json()["stored"] == 2

    page = (await client.get("/api/cards", params={"q": "abundance"}, headers=headers)).json()
    card = (await client.get(f"/api/cards/{page['items'][0]['id']}", headers=headers)).json()
    for printing in card["printings"]:
        image = await client.get(printing["image"], headers=headers)
        assert image.status_code == 200
        assert image.content == PNG
        assert image.headers["content-type"] == "image/png"

    other = (await client.get("/api/cards", params={"q": "aqueduct"}, headers=headers)).json()
    assert other["items"][0]["image"] is None


async def test_remote_image_fetched_once(client, session, synced):
    await make_user(session)
    headers = await bearer(client, "alice")
    printing = await session.scalar(select(Printing).order_by(Printing.id).limit(1))
    printing.image_url = "https://images.test/card.jpg"
    await session.commit()
    with respx.mock as router:
        route = router.get("https://images.test/card.jpg").respond(
            content=b"jpegdata", headers={"content-type": "image/jpeg"}
        )
        for _ in range(2):
            response = await client.get(f"/api/printings/{printing.id}/image", headers=headers)
            assert response.status_code == 200
            assert response.content == b"jpegdata"
        assert route.call_count == 1

    await session.refresh(printing)
    assert printing.image_path.endswith(f"/{printing.id}.jpg")


async def test_remote_image_rejects_non_images(client, session, synced):
    await make_user(session)
    headers = await bearer(client, "alice")
    printing = await session.scalar(select(Printing).order_by(Printing.id).limit(1))
    printing.image_url = "https://images.test/page.html"
    await session.commit()
    with respx.mock as router:
        router.get("https://images.test/page.html").respond(
            content=b"<html>", headers={"content-type": "text/html"}
        )
        response = await client.get(f"/api/printings/{printing.id}/image", headers=headers)
    assert response.status_code == 404


@pytest.mark.smoke
async def test_jobs_record_runs_and_block_overlap(session, sorcery_api):
    from app.main import register_games

    await register_games()
    run_id = await jobs.run_job("sorcery", JobKind.catalog)
    run = await session.get(SyncRun, run_id)
    assert run.status == JobStatus.success
    assert run.report["cards"] == 7

    running = await jobs.start_job("sorcery", JobKind.catalog)
    with pytest.raises(jobs.JobAlreadyRunning):
        await jobs.start_job("sorcery", JobKind.catalog)
    # Another kind or game is not blocked.
    await jobs.start_job("sorcery", JobKind.images)

    # A job stuck for hours is considered dead.
    await session.execute(
        update(SyncRun)
        .where(SyncRun.id == running)
        .values(started_at=datetime.now(UTC) - timedelta(hours=7))
    )
    await session.commit()
    await jobs.start_job("sorcery", JobKind.catalog)
    session.expire_all()
    assert (await session.get(SyncRun, running)).status == JobStatus.failed


async def test_failed_job_is_recorded(session, sorcery_api):
    from app.main import register_games

    await register_games()
    sorcery_api.respond(404)
    with pytest.raises(httpx.HTTPStatusError):
        await jobs.run_job("sorcery", JobKind.catalog)
    run = await session.scalar(select(SyncRun))
    assert run.status == JobStatus.failed
    assert "404" in run.error


async def test_admin_job_endpoints(client, session, sorcery_api):
    await make_user(session, "root", role=Role.admin)
    await make_user(session)
    admin = await bearer(client, "root")
    user = await bearer(client, "alice")

    assert (await client.post("/api/admin/jobs/sorcery/catalog", headers=user)).status_code == 403
    assert (await client.post("/api/admin/jobs/nope/catalog", headers=admin)).status_code == 404
    response = await client.post("/api/admin/jobs/sorcery/catalog", headers=admin)
    assert response.status_code == 202

    runs = (await client.get("/api/admin/jobs", headers=admin)).json()
    assert runs[0]["status"] == "success"
    assert runs[0]["report"]["cards"] == 7

    await jobs.start_job("sorcery", JobKind.catalog)
    response = await client.post("/api/admin/jobs/sorcery/catalog", headers=admin)
    assert response.status_code == 409


async def test_worker_schedule(session):
    from app.main import register_games

    await register_games()
    now = datetime.now(UTC)
    assert await is_due("sorcery", JobKind.catalog, now)

    session.add(SyncRun(game_id="sorcery", kind=JobKind.catalog, status=JobStatus.failed))
    await session.commit()
    assert not await is_due("sorcery", JobKind.catalog, now)  # retry waits an hour
    assert await is_due("sorcery", JobKind.catalog, now + timedelta(hours=2))

    session.add(SyncRun(game_id="sorcery", kind=JobKind.catalog, status=JobStatus.success))
    await session.commit()
    assert not await is_due("sorcery", JobKind.catalog, now + timedelta(hours=2))
    # Catalogs refresh weekly, prices and images daily.
    assert not await is_due("sorcery", JobKind.catalog, now + timedelta(hours=25))
    assert await is_due("sorcery", JobKind.catalog, now + timedelta(hours=169))
    session.add(SyncRun(game_id="sorcery", kind=JobKind.images, status=JobStatus.success))
    await session.commit()
    assert not await is_due("sorcery", JobKind.images, now + timedelta(hours=2))
    assert await is_due("sorcery", JobKind.images, now + timedelta(hours=25))
