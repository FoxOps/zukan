import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import respx
from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.core.http import http_client
from app.core.progress import progress
from app.games.base import get_provider
from app.games.sorcery.provider import IMAGE_URL, parse_cards
from app.models import (
    Card,
    CardName,
    CardSet,
    JobKind,
    JobStatus,
    JobTrigger,
    Printing,
    Role,
    SyncRun,
    User,
)
from app.services import images, jobs, refresh
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
    exact = (
        await client.get(
            "/api/cards",
            params={"game": "sorcery", "color": ["water"], "color_mode": "exact"},
            headers=headers,
        )
    ).json()
    assert [c["name"] for c in exact["items"]] == ["Abundance"]

    sets = (await client.get("/api/games/sorcery/sets", headers=headers)).json()
    promo = next(s for s in sets if s["code"] == "999")
    in_promo = (
        await client.get("/api/cards", params={"set_id": promo["id"]}, headers=headers)
    ).json()
    assert in_promo["total"] == 4

    async def order(**params) -> list[str]:
        page = await client.get(
            "/api/cards", params={"set_id": promo["id"], **params}, headers=headers
        )
        return [c["name"] for c in page.json()["items"]]

    by_name = await order(sort="name")
    assert by_name == sorted(by_name)
    assert await order(sort="name", order="desc") == by_name[::-1]
    by_number = await order(sort="number")
    assert await order(sort="number", order="desc") == by_number[::-1]

    paged = (
        await client.get("/api/cards", params={"page_size": 3, "page": 3}, headers=headers)
    ).json()
    assert paged["total"] == 7 and len(paged["items"]) == 1

    card_id = page["items"][0]["id"]
    card = (await client.get(f"/api/cards/{card_id}", headers=headers)).json()
    assert [p["set"]["code"] for p in card["printings"]] == ["002", "001"]
    assert card["printings"][0]["names"] == {"en": "Abundance"}
    assert (
        card["printings"][0]["image"]
        == f"/api/printings/{card['printings'][0]['id']}/image?lang=en"
    )
    assert card["attributes"]["thresholds"]["water"] >= 1
    # With a set chosen, the image is the printing of that set.
    for printing in card["printings"]:
        found = (
            await client.get(
                "/api/cards", params={"q": "abun", "set_id": printing["set"]["id"]}, headers=headers
            )
        ).json()
        assert found["items"][0]["image"] == printing["image"]
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

    # Not imported: downloaded from the publisher's image URL, which does not have it.
    other = (await client.get("/api/cards", params={"q": "aqueduct"}, headers=headers)).json()
    with respx.mock as router:
        missing = router.get(url__startswith=IMAGE_URL).respond(403)
        for _ in range(2):
            assert (
                await client.get(other["items"][0]["image"], headers=headers)
            ).status_code == 404
        assert missing.call_count == 1  # remembered as missing


async def test_remote_image_fetched_once(client, session, synced):
    await make_user(session)
    headers = await bearer(client, "alice")
    printing = await session.scalar(select(Printing).order_by(Printing.id).limit(1))
    printing.image_urls = {"en": "https://images.test/card.jpg"}
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
    assert printing.image_paths["en"].endswith(f"/{printing.id}-en.jpg")


async def test_remote_image_rejects_non_images(client, session, synced):
    await make_user(session)
    headers = await bearer(client, "alice")
    printing = await session.scalar(select(Printing).order_by(Printing.id).limit(1))
    printing.image_urls = {"en": "https://images.test/page.html"}
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

    # A job without heartbeat for longer than a stall is considered dead.
    await session.execute(
        update(SyncRun)
        .where(SyncRun.id == running)
        .values(heartbeat_at=datetime.now(UTC) - timedelta(minutes=25))
    )
    await session.commit()
    restarted = await jobs.start_job("sorcery", JobKind.catalog)
    session.expire_all()
    assert (await session.get(SyncRun, running)).status == JobStatus.failed

    # Runs of an earlier instance of this process are failed when it starts again.
    await session.execute(
        update(SyncRun).where(SyncRun.id == restarted).values(owner="api:earlier")
    )
    await session.commit()
    assert await jobs.reap_runs() == 1
    session.expire_all()
    assert "stopped" in (await session.get(SyncRun, restarted)).error


@pytest.fixture
def quick_jobs(monkeypatch):
    """Jobs checked often, with a fake job body (`body` is replaced by tests)."""
    monkeypatch.setattr(jobs, "CHECK_EVERY", 0.05)
    monkeypatch.setattr(jobs, "TAKEOVER_WAIT", 5)
    state = {"body": None, "started": asyncio.Event()}

    async def execute(game_id, kind):
        state["started"].set()
        return await state["body"]()

    monkeypatch.setattr(jobs, "_execute", execute)
    return state


async def _busy() -> dict:
    while True:
        await progress()
        await asyncio.sleep(0.01)


async def test_stuck_job_is_stopped(session, quick_jobs, monkeypatch):
    from app.main import register_games

    await register_games()
    monkeypatch.setattr(jobs, "STALL_AFTER", timedelta(seconds=0.2))

    async def hang() -> dict:
        await asyncio.sleep(3600)
        return {}

    quick_jobs["body"] = hang
    with pytest.raises(jobs.JobStopped):
        await jobs.run_job("sorcery", JobKind.catalog)
    run = await session.scalar(select(SyncRun))
    assert run.status == JobStatus.failed and run.error.startswith("Stuck")

    # Progress keeps a job alive, up to its time limit.
    monkeypatch.setitem(jobs.TIME_LIMITS, JobKind.images, timedelta(seconds=0.5))
    quick_jobs["body"] = _busy
    with pytest.raises(jobs.JobStopped):
        await jobs.run_job("sorcery", JobKind.images)
    run = await session.scalar(select(SyncRun).where(SyncRun.kind == JobKind.images))
    assert run.status == JobStatus.failed and run.error.startswith("Timed out")


async def test_manual_run_takes_over_auto_run(session, quick_jobs):
    from app.main import register_games

    await register_games()
    quick_jobs["body"] = _busy
    auto = asyncio.create_task(jobs.run_job("sorcery", JobKind.catalog, JobTrigger.auto))
    await quick_jobs["started"].wait()

    async def done() -> dict:
        return {"cards": 1}

    quick_jobs["body"] = done
    manual = await jobs.run_job("sorcery", JobKind.catalog)
    with pytest.raises(jobs.JobStopped):
        await auto
    runs = {r.trigger: r for r in await session.scalars(select(SyncRun))}
    assert runs[JobTrigger.auto].status == JobStatus.cancelled
    assert runs[JobTrigger.manual].id == manual
    assert runs[JobTrigger.manual].status == JobStatus.success

    # An auto run never takes over.
    quick_jobs["body"] = _busy
    quick_jobs["started"].clear()
    running = asyncio.create_task(jobs.run_job("sorcery", JobKind.images))
    await quick_jobs["started"].wait()
    with pytest.raises(jobs.JobAlreadyRunning):
        await jobs.start_job("sorcery", JobKind.images, JobTrigger.auto)
    running.cancel()


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
    assert runs[0]["elapsed_seconds"] >= 0

    await jobs.start_job("sorcery", JobKind.catalog)
    running = (await client.get("/api/admin/jobs", headers=admin)).json()[0]
    assert running["status"] == "running" and running["elapsed_seconds"] >= 0
    response = await client.post("/api/admin/jobs/sorcery/catalog", headers=admin)
    assert response.status_code == 409


async def test_worker_schedule(session):
    from app.main import register_games

    await register_games()
    now = datetime.now(UTC)
    assert await is_due("sorcery", JobKind.catalog, now)

    def auto(**values) -> SyncRun:
        return SyncRun(game_id="sorcery", trigger=JobTrigger.auto, **values)

    # Manual runs do not count.
    session.add(SyncRun(game_id="sorcery", kind=JobKind.catalog, status=JobStatus.failed))
    await session.commit()
    assert await is_due("sorcery", JobKind.catalog, now)
    session.add(auto(kind=JobKind.catalog, status=JobStatus.cancelled))
    await session.commit()
    assert await is_due("sorcery", JobKind.catalog, now)  # cancelled: retried at once

    session.add(auto(kind=JobKind.catalog, status=JobStatus.failed))
    await session.commit()
    assert not await is_due("sorcery", JobKind.catalog, now)  # retry waits an hour
    assert await is_due("sorcery", JobKind.catalog, now + timedelta(hours=2))

    # A catalog synced by an older version of the provider is synced again at once.
    session.add(auto(kind=JobKind.catalog, status=JobStatus.success))
    await session.commit()
    assert await is_due("sorcery", JobKind.catalog, now + timedelta(hours=2))
    current = {"catalog_version": get_provider("sorcery").catalog_version}
    session.add(auto(kind=JobKind.catalog, status=JobStatus.success, report=current))
    await session.commit()
    assert not await is_due("sorcery", JobKind.catalog, now + timedelta(hours=2))
    # Catalogs refresh weekly, prices and images daily.
    assert not await is_due("sorcery", JobKind.catalog, now + timedelta(hours=25))
    assert await is_due("sorcery", JobKind.catalog, now + timedelta(hours=169))
    session.add(auto(kind=JobKind.images, status=JobStatus.success))
    await session.commit()
    assert not await is_due("sorcery", JobKind.images, now + timedelta(hours=2))
    assert await is_due("sorcery", JobKind.images, now + timedelta(hours=25))
    # A newer catalog may bring new image URLs.
    session.add(auto(kind=JobKind.catalog, status=JobStatus.success, report=current))
    await session.commit()
    assert await is_due("sorcery", JobKind.images, now + timedelta(hours=2))


async def test_image_job_reports_printings_without_source(session, synced):
    total = await session.scalar(select(func.count()).select_from(Printing))
    # A database upgraded from 0.2: no image URL until the catalog is synced again.
    await session.execute(update(Printing).values(image_urls={}))
    await session.commit()
    async with http_client() as http:
        report = await images.cache_images(session, http, "sorcery")
    assert (report.stored, report.failed, report.missing) == (0, 0, total)


async def test_image_job_counts_every_printing(session, synced):
    total = await session.scalar(select(func.count()).select_from(Printing))
    with respx.mock(assert_all_mocked=False) as router:
        router.get(url__startswith=IMAGE_URL).respond(
            200, content=PNG, headers={"content-type": "image/png"}
        )
        async with http_client() as http:
            first = await images.cache_images(session, http, "sorcery")
            # Nothing left to download: a second run says why it did nothing.
            second = await images.cache_images(session, http, "sorcery")
    assert (first.printings, first.stored) == (total, total)
    assert (second.printings, second.cached, second.stored) == (total, total, 0)


async def test_catalog_sync_prunes_cards_without_printings(session, synced):
    report = await sync_sorcery(session)
    assert report.catalog_version == get_provider("sorcery").catalog_version
    session.add(Card(game_id="sorcery", external_id="orphan", name="Orphan", colors=[]))
    await session.commit()
    assert (await sync_sorcery(session)).pruned_cards == 1
    assert await session.scalar(select(Card).where(Card.external_id == "orphan")) is None


async def test_search_by_set_abbreviation(client, session, synced):
    await make_user(session)
    headers = await bearer(client, "alice")
    by_set = {}
    for query in ("sorcery ALP", "alp", "sorcery 001"):
        page = (await client.get("/api/cards", params={"q": query}, headers=headers)).json()
        by_set[query] = {c["name"] for c in page["items"]}
        assert by_set[query], query
    assert by_set["sorcery ALP"] == by_set["alp"] == by_set["sorcery 001"]


async def test_sorcery_refresh_downloads_the_catalog_once(session, synced, sorcery_api):
    from app.games.sorcery import provider as sorcery

    sorcery._cached_catalog = None
    calls = sorcery_api.call_count
    card_ids = list(await session.scalars(select(Card.id).order_by(Card.id).limit(2)))
    await session.execute(update(Card).where(Card.id.in_(card_ids)).values(attributes={}))
    await session.commit()
    async with http_client() as http:
        for card_id in card_ids:
            report = await refresh.refresh_cards(session, get_provider("sorcery"), http, [card_id])
            assert (report.updated, report.not_found) == (1, 0)
    assert sorcery_api.call_count == calls + 1
    session.expire_all()
    for card_id in card_ids:
        assert (await session.get(Card, card_id)).attributes


async def test_price_source_plugin_with_its_own_api(client, session, synced, monkeypatch):
    """A market plugin fetching its own prices, matched through market ids."""
    from app.games.base import PriceQuote
    from app.prices import base as price_base

    printing = await session.scalar(select(Printing).order_by(Printing.id).limit(1))
    printing.attributes = {**printing.attributes, "market_ids": {"nexus": 42}}
    await session.commit()

    class Nexus:
        id = "nexus"
        name = "Nexus"
        currency = "EUR"
        games = {"sorcery"}

        def link(self, game_id, market_id, lang):
            return f"https://nexus.example/p/{market_id}"

        async def fetch(self, http, game_id, targets):
            yield [
                PriceQuote(t.set_external_id, t.printing_external_id, t.finishes[0],
                           Decimal("3.30"), source="nexus")
                for t in targets
                if t.market_ids.get("nexus") == 42
            ]  # fmt: skip

    sources = dict(price_base.price_sources()) | {"nexus": Nexus()}
    monkeypatch.setattr(price_base, "price_sources", lambda: sources)
    from app.services import prices

    monkeypatch.setattr(prices, "price_sources", lambda: sources)
    monkeypatch.setattr("app.api.catalog.price_sources", lambda: sources)
    monkeypatch.setattr("app.api.auth.price_sources", lambda: sources)

    async def no_cardmarket(self, http, owned):
        return
        yield

    monkeypatch.setattr(type(get_provider("sorcery")), "fetch_prices", no_cardmarket)
    async with http_client() as http:
        report = await prices.sync_prices(session, get_provider("sorcery"), http)
    assert report.stored == 1

    await make_user(session)
    headers = await bearer(client, "alice")
    games = (await client.get("/api/games", headers=headers)).json()
    sorcery = next(g for g in games if g["id"] == "sorcery")
    assert [s["id"] for s in sorcery["price_sources"]] == ["cardmarket", "nexus"]

    async def shown() -> tuple[list[dict], list[dict], set[str]]:
        card = (await client.get(f"/api/cards/{printing.card_id}", headers=headers)).json()
        ours = next(p for p in card["printings"] if p["id"] == printing.id)
        history = (await client.get(f"/api/printings/{printing.id}/prices", headers=headers)).json()
        return ours["links"], ours["prices"], {p["source"] for p in history}

    # Only the user's sources are shown (Cardmarket by default).
    links, quotes, history = await shown()
    assert all(link["source"] != "nexus" for link in links)
    assert all(p["source"] != "nexus" for p in quotes) and "nexus" not in history

    me = await client.patch(
        "/api/auth/me", json={"price_sources": ["nexus", "cardmarket"]}, headers=headers
    )
    assert me.json()["price_sources"] == ["nexus", "cardmarket"]
    assert me.json()["price_source"] == "nexus"
    links, quotes, history = await shown()
    assert {"source": "nexus", "name": "Nexus", "url": "https://nexus.example/p/42"} in links
    # Main source first.
    assert quotes[0]["source"] == "nexus" and quotes[0]["trend"] == "3.30"
    assert "nexus" in history
    empty = await client.patch("/api/auth/me", json={"price_sources": []}, headers=headers)
    assert empty.status_code == 422


async def test_advanced_search_filters(client, session, synced):
    await make_user(session)
    headers = await bearer(client, "alice")
    games = (await client.get("/api/games", headers=headers)).json()
    sorcery = next(g for g in games if g["id"] == "sorcery")
    assert [f["key"] for f in sorcery["filters"]] == ["category", "type", "subtypes", "rarity"]
    values = (await client.get("/api/games/sorcery/filters", headers=headers)).json()
    assert values["type"] == ["Artifact", "Aura", "Avatar", "Minion", "Site"]
    assert values["subtypes"] == ["Mortal", "Relic"]
    assert "Elite" in values["rarity"]

    async def names(*attrs: str) -> set[str]:
        page = await client.get(
            "/api/cards", params={"game": "sorcery", "attr": list(attrs)}, headers=headers
        )
        return {c["name"] for c in page.json()["items"]}

    assert await names("type:Avatar") == {"Archimago", "Druid", "Avatar of Air"}
    assert await names("subtypes:Relic") == {"13 Treasures of Britain"}
    assert await names("category:Spell", "subtypes:Mortal") == {"Amazon Warriors"}
    assert await names("rarity:Elite") == {"Abundance"}
    bad = await client.get("/api/cards", params={"game": "sorcery", "attr": "x:y"}, headers=headers)
    assert bad.status_code == 422
    bad = await client.get("/api/cards", params={"attr": "type:Avatar"}, headers=headers)
    assert bad.status_code == 422


def test_cross_check_comparison_ignores_spelling():
    from app.games.base import compare

    for a, b in (("Genesect EX", "Genesect-EX"), ("Vaporeon ☆", "Vaporeon ★"), ("Forêt", "foret")):
        assert compare("s", "1", "name", a, b) is None
    assert compare("s", "1", "name", "Uxie", "Uxie LV.X") is not None
    assert compare("s", "1", "rarity", "Holo Rare", "Rare Holo", words=True) is None
    assert compare("s", "1", "rarity", "Rare", "Rare Holo EX", words=True) is None
    assert compare("s", "1", "rarity", "Common", "Promo", words=True) is not None
    assert compare("s", "1", "rarity", None, "Promo") is None


async def test_reset_catalog_keeps_owned_printings(client, session, sorcery_api):
    from app.models import CollectionItem

    await make_user(session, "root", role=Role.admin)
    admin = await bearer(client, "root")
    await sync_sorcery(session)
    printings = (await session.scalars(select(Printing).order_by(Printing.id))).all()
    owned, other = printings[0], printings[1]
    owned_id, other_id = owned.id, other.id
    user_id = await session.scalar(select(User.id).where(User.username == "root"))
    session.add(
        CollectionItem(user_id=user_id, printing_id=owned_id, finish=owned.finishes[0],
                       language="en", quantity=1)
    )  # fmt: skip
    root = get_settings().image_dir
    files = [
        root / "sorcery" / str(owned.set_id) / f"{owned_id}-en.webp",
        root / "sorcery" / str(other.set_id) / f"{other_id}-en.webp",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    await session.commit()
    total = len(printings)

    response = await client.post("/api/admin/games/sorcery/reset", headers=admin)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kept"] == 1 and body["printings"] == total - 1
    assert files[0].exists() and not files[1].exists()
    session.expire_all()
    # The catalog job ran again (test client runs background tasks): everything is back.
    assert await session.scalar(select(func.count()).select_from(Printing)) == total
    assert await session.get(Printing, owned_id) is not None
    runs = (await client.get("/api/admin/jobs", headers=admin)).json()
    assert runs[0]["id"] == body["run_id"] and runs[0]["status"] == "success"


async def test_next_run_and_schedule(client, session, synced):
    from app.services.schedule import RETRY_AFTER, next_run

    now = datetime.now(UTC)
    # Never run by the worker: at its next check.
    assert await next_run("sorcery", JobKind.catalog, now) == now
    run = SyncRun(
        game_id="sorcery",
        kind=JobKind.catalog,
        trigger=JobTrigger.auto,
        status=JobStatus.success,
        started_at=now - timedelta(hours=1),
        report={"catalog_version": get_provider("sorcery").catalog_version},
    )
    session.add(run)
    await session.commit()
    assert await next_run("sorcery", JobKind.catalog, now) == run.started_at + timedelta(days=7)
    failed = SyncRun(
        game_id="sorcery",
        kind=JobKind.images,
        trigger=JobTrigger.auto,
        status=JobStatus.failed,
        started_at=now - timedelta(minutes=10),
    )
    session.add(failed)
    await session.commit()
    assert await next_run("sorcery", JobKind.images, now) == failed.started_at + RETRY_AFTER

    await make_user(session, "root", role=Role.admin)
    admin = await bearer(client, "root")
    schedule = (await client.get("/api/admin/schedule", headers=admin)).json()
    kinds = {(s["game_id"], s["kind"]) for s in schedule}
    assert ("sorcery", "catalog") in kinds and ("sorcery", "refresh") in kinds


async def test_stale_cards_listed_and_refreshed(client, session, synced, sorcery_api):
    card = await session.scalar(select(Card).where(Card.name == "Abundance"))
    card.attributes = {}
    await session.commit()
    await make_user(session, "root", role=Role.admin)
    admin = await bearer(client, "root")
    page = (await client.get("/api/admin/stale", params={"game": "sorcery"}, headers=admin)).json()
    assert [(c["name"], c["reasons"]) for c in page["items"]] == [("Abundance", ["no_attributes"])]
    assert "sorcery" in page["refreshable"]

    done = await client.post(f"/api/admin/cards/{card.id}/refresh", headers=admin)
    assert done.json() == {"updated": True, "stale": False}
    page = (await client.get("/api/admin/stale", params={"game": "sorcery"}, headers=admin)).json()
    assert page["total"] == 0
