import gzip
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import func, select, update

from app.core.http import http_client
from app.games.base import get_provider
from app.games.cardmarket import DOWNLOAD_URL as CARDMARKET_URL
from app.games.mtg.provider import API_URL, iter_jsonl_gz, parse_card
from app.main import register_games
from app.models import (
    Card,
    CardName,
    CardSet,
    CollectionItem,
    JobKind,
    JobStatus,
    PriceSnapshot,
    Printing,
    Role,
    SyncRun,
)
from app.services import jobs
from app.services.catalog import sync_catalog
from app.services.prices import today
from tests.conftest import bearer, make_user

FIXTURES = Path(__file__).parent / "fixtures"
SETS = json.loads((FIXTURES / "mtg_sets.json").read_text())
LINES = (FIXTURES / "mtg_cards.jsonl").read_text().splitlines()
RAW = [json.loads(line) for line in LINES]
ALL_URL = "https://data.scryfall.io/all-cards/all.jsonl.gz"
DEFAULT_URL = "https://data.scryfall.io/default-cards/default.jsonl.gz"


def raw(lang: str, set_code: str) -> dict:
    return next(c for c in RAW if c["lang"] == lang and c["set"] == set_code)


def gz(lines: list[str]) -> bytes:
    return gzip.compress(("\n".join(lines) + "\n").encode())


@pytest.fixture
def scryfall():
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{API_URL}/sets").respond(json=SETS)
        router.get(f"{API_URL}/bulk-data/all_cards").respond(
            json={"jsonl_download_uri": ALL_URL, "compressed_size": 1}
        )
        router.get(f"{API_URL}/bulk-data/default_cards").respond(
            json={"jsonl_download_uri": DEFAULT_URL}
        )
        router.get(ALL_URL).respond(content=gz(LINES))
        english = [line for line, c in zip(LINES, RAW, strict=True) if c["lang"] == "en"]
        router.get(DEFAULT_URL).respond(content=gz(english + [LINES[6]]))  # + JA-only Ajani
        # Cardmarket price guide: Llanowar Elves (319744); trend 0 = none, foil has no trend.
        guide = {"idProduct": 319744, "trend": 0, "low": 0.1, "avg": 0.45, "low-foil": 1.2}
        router.get(f"{CARDMARKET_URL}/priceGuide/price_guide_1.json").respond(
            json={"version": 1, "priceGuides": [guide]}
        )
        yield router


async def sync_mtg(session):
    await register_games()
    async with http_client() as http:
        return await sync_catalog(session, get_provider("mtg"), http)


async def printing(session, set_code: str, number: str) -> Printing:
    """Fresh printing row (expires previously loaded objects: keep ids, not objects)."""
    session.expire_all()
    return await session.scalar(
        select(Printing)
        .join(CardSet)
        .where(CardSet.game_id == "mtg", CardSet.external_id == set_code)
        .where(Printing.external_id == number)
    )


def test_parse_card():
    elves = parse_card(raw("en", "dom"))
    assert elves.colors == ["G"] and not elves.partial
    assert elves.names == {"en": "Llanowar Elves"}
    assert elves.printings[0].names == {}
    assert elves.printings[0].attributes["scryfall_id"] == raw("en", "dom")["id"]

    french = parse_card(raw("fr", "dom"))
    assert french.partial
    assert french.printings[0].names == {"fr": "Elfes de Llanowar"}
    assert french.printings[0].attributes == {}

    delver = parse_card(raw("en", "isd"))
    assert [f["name"] for f in delver.attributes["faces"]] == [
        "Delver of Secrets",
        "Insectile Aberration",
    ]
    assert delver.colors == ["U"]
    assert delver.printings[0].images["en"].startswith("https://cards.scryfall.io/normal/front/")
    assert "/back/" in delver.printings[0].attributes["back_image_url"]
    assert parse_card(raw("fr", "isd")).printings[0].names["fr"].startswith("Sondeur de secrets")

    assert parse_card(raw("en", "ymid")) is None  # Arena only
    assert parse_card(raw("ph", "dmu")) is None  # unsupported language


async def test_jsonl_stream_in_small_chunks():
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            data = gz(LINES)
            for start in range(0, len(data), 7):
                yield data[start : start + 7]

    response = httpx.Response(200, stream=Chunks())
    assert [c["id"] async for c in iter_jsonl_gz(response)] == [c["id"] for c in RAW]


@pytest.mark.smoke
async def test_sync_merges_languages(client, session, scryfall):
    report = await sync_mtg(session)
    assert report.sets == 4  # digital set skipped
    assert await session.scalar(select(func.count()).select_from(Card)) == 3

    elves = await printing(session, "dom", "168")
    elves_id = elves.id
    card = await session.get(Card, elves.card_id)
    assert (card.attributes["types"], card.attributes["subtypes"]) == (
        ["Creature"],
        ["Elf", "Druid"],
    )
    assert set(elves.languages) == {"en", "fr", "de"}
    # One scan per language, whatever the order of the objects.
    assert elves.image_urls == {
        lang: raw(lang, "dom")["image_uris"]["normal"] for lang in ("en", "fr", "de")
    }
    assert elves.attributes["scryfall_id"] == raw("en", "dom")["id"]

    ajani = await printing(session, "war", "184★")
    assert ajani.languages == ["ja"]
    assert ajani.image_urls == {"ja": raw("ja", "war")["image_uris"]["normal"]}

    names = set(await session.scalars(select(CardName.name).where(CardName.lang == "fr")))
    assert {"Elfes de Llanowar", "Sondeur de secrets // Aberration insectoïde"} <= names

    snapshot = await session.scalar(
        select(PriceSnapshot).where(
            PriceSnapshot.printing_id == elves_id, PriceSnapshot.finish == "nonfoil"
        )
    )
    assert snapshot.trend == Decimal("0.39") and snapshot.date == today()
    # Elves, delver and ajani, nonfoil and foil, on Cardmarket and TCGplayer.
    assert report.prices == 12
    tcgplayer = await session.scalar(
        select(PriceSnapshot).where(
            PriceSnapshot.printing_id == elves_id,
            PriceSnapshot.finish == "nonfoil",
            PriceSnapshot.source == "tcgplayer",
        )
    )
    assert tcgplayer.currency == "USD" and tcgplayer.trend > 0

    counts = [
        await session.scalar(select(func.count()).select_from(m))
        for m in (CardSet, Card, Printing, CardName, PriceSnapshot)
    ]
    await sync_mtg(session)
    assert [
        await session.scalar(select(func.count()).select_from(m))
        for m in (CardSet, Card, Printing, CardName, PriceSnapshot)
    ] == counts

    await make_user(session)
    headers = await bearer(client, "alice")
    for query in ("Elfes", "llanowarelfen", "llanowar"):
        page = (await client.get("/api/cards", params={"q": query}, headers=headers)).json()
        assert [c["name"] for c in page["items"]] == ["Llanowar Elves"], query
    # Set code and collector number, with or without the game.
    for query in ("mtg dom 168", "DOM 168", "magic dom"):
        page = (await client.get("/api/cards", params={"q": query}, headers=headers)).json()
        assert [c["name"] for c in page["items"]] == ["Llanowar Elves"], query
    page = (await client.get("/api/cards", params={"q": "mtg isd 51"}, headers=headers)).json()
    assert [c["name"] for c in page["items"]] == ["Delver of Secrets // Insectile Aberration"]
    page = (await client.get("/api/cards", params={"q": "pkm dom 168"}, headers=headers)).json()
    assert page["items"] == []


async def test_language_order_does_not_matter(session, scryfall):
    scryfall.get(ALL_URL).respond(content=gz(list(reversed(LINES))))
    await sync_mtg(session)
    elves = await printing(session, "dom", "168")
    assert elves.image_urls["en"] == raw("en", "dom")["image_uris"]["normal"]
    assert set(elves.languages) == {"en", "fr", "de"}


async def test_price_job_keeps_history_of_owned_cards(session, scryfall):
    await sync_mtg(session)
    user_id = (await make_user(session)).id
    elves = (await printing(session, "dom", "168")).id
    delver = (await printing(session, "isd", "51")).id
    session.add(
        CollectionItem(user_id=user_id, printing_id=elves, finish="foil", language="en", quantity=1)
    )
    yesterday = today() - timedelta(days=1)
    for printing_id in (elves, delver):
        session.add(
            PriceSnapshot(
                printing_id=printing_id,
                finish="nonfoil",
                date=yesterday,
                source="cardmarket",
                trend=Decimal("9.99"),
            )
        )
    await session.commit()

    run = await session.get(SyncRun, await jobs.run_job("mtg", JobKind.prices))
    assert run.report["stored"] == 12
    assert run.report["pruned"] == 1
    # Scryfall's trend, Cardmarket's lowest offer and average.
    latest = {
        s.finish: (s.trend, s.low, s.avg)
        for s in await session.scalars(
            select(PriceSnapshot).where(
                PriceSnapshot.printing_id == elves,
                PriceSnapshot.date == today(),
                PriceSnapshot.source == "cardmarket",
            )
        )
    }
    assert latest == {
        "nonfoil": (Decimal("0.39"), Decimal("0.10"), Decimal("0.45")),
        "foil": (Decimal("1.69"), Decimal("1.20"), None),
    }

    old = await session.scalars(
        select(PriceSnapshot.printing_id).where(PriceSnapshot.date == yesterday)
    )
    assert list(old) == [elves]  # delver is not owned: only its latest price is kept


async def test_stale_card_is_refreshed(client, session, scryfall):
    await sync_mtg(session)
    elves = raw("en", "dom")
    oracle = elves["oracle_id"]
    prints = [c for c in RAW if c.get("oracle_id") == oracle]
    # Two result pages, as Scryfall pages its searches.
    search = scryfall.get(f"{API_URL}/cards/search")
    search.side_effect = [
        httpx.Response(
            200, json={"data": prints[:1], "has_more": True, "next_page": f"{API_URL}/p2"}
        ),
    ]
    scryfall.get(f"{API_URL}/p2").respond(json={"data": prints[1:], "has_more": False})

    # Image URLs lost (an older catalog): the card is stale.
    card = await session.scalar(select(Card).where(Card.external_id == oracle))
    card_id = card.id
    await session.execute(update(Printing).where(Printing.card_id == card_id).values(image_urls={}))
    await session.commit()

    await make_user(session)
    headers = await bearer(client, "alice")
    detail = (await client.get(f"/api/cards/{card_id}", headers=headers)).json()
    assert detail["refreshing"] is True
    assert search.calls[0].request.url.params["q"] == f"oracleid:{oracle}"
    # The refresh ran after the answer: images are back, and no new refresh for a while.
    assert (await printing(session, "dom", "168")).image_urls["en"]
    detail = (await client.get(f"/api/cards/{card_id}", headers=headers)).json()
    assert detail["refreshing"] is False


async def test_refresh_job_fetches_cards_missed_by_the_last_sync(session, scryfall):
    await sync_mtg(session)
    now = datetime.now(UTC)
    session.add(
        SyncRun(
            game_id="mtg",
            kind=JobKind.catalog,
            status=JobStatus.success,
            started_at=now - timedelta(hours=26),
            finished_at=now - timedelta(hours=25),
        )
    )
    elves = raw("en", "dom")
    await session.execute(
        update(Card)
        .where(Card.external_id == elves["oracle_id"])
        .values(last_seen_at=now - timedelta(days=3))
    )
    await session.commit()
    scryfall.get(f"{API_URL}/cards/search").respond(
        json={"data": [c for c in RAW if c.get("oracle_id") == elves["oracle_id"]]}
    )

    run = await session.get(SyncRun, await jobs.run_job("mtg", JobKind.refresh))
    assert run.report == {"checked": 1, "updated": 1, "not_found": 0}
    session.expire_all()
    card = await session.scalar(select(Card).where(Card.external_id == elves["oracle_id"]))
    assert card.last_seen_at > now - timedelta(minutes=1)
    # Fresh again: the next run has nothing to do.
    run = await session.get(SyncRun, await jobs.run_job("mtg", JobKind.refresh))
    assert run.report == {"checked": 0, "updated": 0, "not_found": 0}


def csv_gz(header: str, *rows: str) -> bytes:
    return gzip.compress(("\n".join([header, *rows]) + "\n").encode())


async def test_mtgjson_fills_gaps_and_reports_discrepancies(client, session, scryfall):
    from app.games.mtg.mtgjson import CSV_URL

    scryfall.get(f"{CSV_URL}/sets.csv.gz").respond(
        content=csv_gz(
            "code,name,releaseDate",
            "DOM,Dominaria,2018-04-27",
            "ISD,Innistrad,2011-09-29",  # one day off
        )
    )
    scryfall.get(f"{CSV_URL}/cardIdentifiers.csv.gz").respond(
        content=csv_gz("uuid,mcmId,tcgplayerProductId", "u-elves,999,162231", "u-delver,,55")
    )
    scryfall.get(f"{CSV_URL}/cards.csv.gz").respond(
        content=csv_gz(
            "setCode,number,name,rarity,artist,uuid,side",
            "DOM,168,Llanowar Elves,uncommon,Chris Rahn,u-elves,",
            "ISD,51,Delver of Secrets // Insectile Aberration,common,Nils Hamm,u-delver,a",
            "ISD,51,Delver of Secrets // Insectile Aberration,common,Nils Hamm,u-delver,b",
            "XXX,1,Unknown,common,Nobody,u-x,",
        )
    )
    run = await session.get(SyncRun, await jobs.run_job("mtg", JobKind.catalog))
    assert run.report["cross_checked"] == 2
    assert run.report["discrepancies"] == 2  # elves rarity, isd release date

    elves = await printing(session, "dom", "168")
    # Scryfall's Cardmarket id is kept, the TCGplayer id it lacked is added.
    assert elves.attributes["market_ids"] == {"cardmarket": 319744, "tcgplayer": 162231}
    assert elves.rarity == "common"  # the primary source wins
    delver = await printing(session, "isd", "51")
    assert delver.attributes["market_ids"] == {"cardmarket": 250620, "tcgplayer": 55}

    await make_user(session, "root", role=Role.admin)
    admin = await bearer(client, "root")
    page = (await client.get("/api/admin/discrepancies", headers=admin)).json()
    found = {(d["set_code"], d["collector_number"], d["field"]): d for d in page["items"]}
    assert set(found) == {("DOM", "168", "rarity"), ("ISD", None, "release date")}
    assert found["DOM", "168", "rarity"]["secondary_value"] == "uncommon"
    count = {"resolved": 0, "rule": None, "rule_id": None}
    assert page["counts"] == [
        {"game_id": "mtg", "source": "mtgjson", "field": "rarity", "count": 1, **count},
        {"game_id": "mtg", "source": "mtgjson", "field": "release date", "count": 1, **count},
    ]

    # Arbitration: MTGJSON's rarity is right; written now and after every sync.
    rarity = found["DOM", "168", "rarity"]
    done = await client.post(
        f"/api/admin/discrepancies/{rarity['id']}/resolve",
        json={"choice": "secondary"},
        headers=admin,
    )
    assert done.json() == {"written": 1}
    session.expire_all()
    assert (await printing(session, "dom", "168")).rarity == "uncommon"
    await jobs.run_job("mtg", JobKind.catalog)
    session.expire_all()
    assert (await printing(session, "dom", "168")).rarity == "uncommon"
    page = (await client.get("/api/admin/discrepancies", headers=admin)).json()
    assert [d["field"] for d in page["items"]] == ["release date"]
    resolved = (
        await client.get("/api/admin/discrepancies", params={"state": "resolved"}, headers=admin)
    ).json()
    assert [(d["field"], d["resolution"]) for d in resolved["items"]] == [("rarity", "secondary")]

    # A rule for the release dates: MTGJSON's, for this one and the next ones.
    rule = await client.put(
        "/api/admin/discrepancies/rules",
        json={
            "game_id": "mtg",
            "source": "mtgjson",
            "field": "release date",
            "prefer": "secondary",
        },
        headers=admin,
    )
    assert rule.status_code == 200
    session.expire_all()
    isd = await session.scalar(select(CardSet).where(CardSet.code == "ISD"))
    assert str(isd.release_date) == "2011-09-29"
    page = (await client.get("/api/admin/discrepancies", headers=admin)).json()
    assert page["items"] == []
    dates = next(c for c in page["counts"] if c["field"] == "release date")
    assert (dates["count"], dates["resolved"], dates["rule"]) == (0, 1, "secondary")
    # Removing the rule opens it again.
    removed = await client.delete(
        f"/api/admin/discrepancies/rules/{dates['rule_id']}", headers=admin
    )
    assert removed.status_code == 204
    page = (await client.get("/api/admin/discrepancies", headers=admin)).json()
    assert [d["field"] for d in page["items"]] == ["release date"]

    # Back to the primary for the rarity: reopened, Scryfall's value is back.
    await client.post(
        f"/api/admin/discrepancies/{rarity['id']}/resolve", json={"choice": None}, headers=admin
    )
    session.expire_all()
    assert (await printing(session, "dom", "168")).rarity == "common"

    # Fixed upstream: the next run drops the discrepancy.
    scryfall.get(f"{CSV_URL}/cards.csv.gz").respond(
        content=csv_gz(
            "setCode,number,name,rarity,artist,uuid,side",
            "DOM,168,Llanowar Elves,common,Chris Rahn,u-elves,",
        )
    )
    await jobs.run_job("mtg", JobKind.catalog)
    page = (await client.get("/api/admin/discrepancies", headers=admin)).json()
    assert [d["field"] for d in page["items"]] == ["release date"]


async def test_set_icons_and_back_faces_are_served_locally(
    client, session, scryfall, tmp_path, monkeypatch
):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "image_dir", tmp_path)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"/>'
    icon = scryfall.get(url__startswith="https://svgs.scryfall.io/sets/").respond(
        content=svg, headers={"content-type": "image/svg+xml"}
    )
    back = scryfall.get(url__startswith="https://cards.scryfall.io/").respond(
        content=b"\x89PNG\r\n\x1a\n0000", headers={"content-type": "image/png"}
    )
    await sync_mtg(session)
    await make_user(session)
    headers = await bearer(client, "alice")
    delver = await printing(session, "isd", "51")
    card = (await client.get(f"/api/cards/{delver.card_id}", headers=headers)).json()
    ours = card["printings"][0]
    assert ours["set"]["icon"] == f"/api/sets/{ours['set']['id']}/icon"
    assert ours["back_image"] == f"/api/printings/{ours['id']}/image?face=back"

    for _ in range(2):  # downloaded once, then from the cache
        response = await client.get(ours["set"]["icon"], headers=headers)
        assert response.content == svg
        assert "default-src 'none'" in response.headers["content-security-policy"]
    assert icon.call_count == 1
    response = await client.get(ours["back_image"], headers=headers)
    assert response.status_code == 200 and back.call_count == 1
    elves = await printing(session, "dom", "168")
    no_back = await client.get(f"/api/printings/{elves.id}/image?face=back", headers=headers)
    assert no_back.status_code == 404
