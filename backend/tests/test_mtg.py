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
