import json
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest
import respx
from sqlalchemy import func, select

from app.core.http import http_client
from app.games.base import get_provider
from app.games.pokemon.provider import API_URL, parse_prices
from app.main import register_games
from app.models import (
    Card,
    CardName,
    CardSet,
    CollectionItem,
    JobKind,
    PriceSnapshot,
    Printing,
    SyncRun,
)
from app.services import jobs
from app.services.catalog import sync_catalog
from tests.conftest import bearer, make_user

API = json.loads((Path(__file__).parent / "fixtures" / "pokemon_api.json").read_text())


@pytest.fixture(autouse=True)
def languages(monkeypatch):
    monkeypatch.setenv("TCG_POKEMON_LANGUAGES", '["en", "fr", "ja"]')


@pytest.fixture
def tcgdex():
    def respond(request: httpx.Request) -> httpx.Response:
        # Like the real server, a literal "+" in the path means a space.
        raw = request.url.raw_path.decode().split("?")[0].replace("+", " ")
        path = unquote(raw).removeprefix("/v2")
        if path in API:
            return httpx.Response(200, json=API[path])
        return httpx.Response(404, json={"error": "not found"})

    with respx.mock(assert_all_called=False) as router:
        route = router.get(url__startswith=API_URL).mock(side_effect=respond)
        yield route


async def sync_pokemon(session):
    await register_games()
    async with http_client() as http:
        return await sync_catalog(session, get_provider("pokemon"), http)


async def printing_id(session, set_id: str, local_id: str) -> int:
    return await session.scalar(
        select(Printing.id)
        .join(CardSet)
        .where(CardSet.game_id == "pokemon", CardSet.external_id == set_id)
        .where(Printing.external_id == local_id)
    )


def test_prices_map_to_finishes():
    furret = API["/en/cards/swsh3-136"]  # normal + reverse
    market = furret["pricing"]["cardmarket"]
    quotes = {q.finish: q for q in parse_prices(furret, "swsh3")}
    assert quotes["normal"].trend == Decimal(str(market["trend"]))
    assert quotes["reverse"].trend == Decimal(str(market["trend-holo"]))

    heatran = API["/en/cards/swsh3-25"]  # holo rare + reverse
    market = heatran["pricing"]["cardmarket"]
    quotes = {q.finish: q for q in parse_prices(heatran, "swsh3")}
    assert set(quotes) == {"holo", "reverse"}
    assert quotes["holo"].low == Decimal(str(market["low"]))

    assert parse_prices({"localId": "1", "variants": {"normal": True}}, "x") == []


@pytest.mark.smoke
async def test_sync_sets_translations_and_exclusive_sets(client, session, tcgdex):
    report = await sync_pokemon(session)
    sets = {s.external_id: s for s in await session.scalars(select(CardSet))}
    assert set(sets) == {"swsh3", "hgss1", "SV1a", "SM1+"}
    assert sets["swsh3"].code == "DAA" and sets["swsh3"].lang is None
    assert sets["SV1a"].lang == "ja"

    cards = {c.external_id: c for c in await session.scalars(select(Card))}
    assert set(cards) == {
        "en:furret",
        "en:heatran",
        "en:spikemuth",
        "fr:dracaufeu v",
        "ja:トロピウス",
    }
    assert cards["en:furret"].colors == ["colorless"]
    assert cards["en:spikemuth"].colors == []
    assert cards["en:spikemuth"].attributes["category"] == "Trainer"
    assert cards["ja:トロピウス"].colors == ["grass"]

    furret = await session.get(Printing, await printing_id(session, "swsh3", "136"))
    assert furret.languages == ["en", "fr"]
    assert furret.finishes == ["normal", "reverse"]
    assert furret.image_url == "https://assets.tcgdex.net/en/swsh/swsh3/136/high.webp"
    assert furret.rarity == "Uncommon"  # translation did not clear details
    assert (
        len([p for p in await session.scalars(select(Printing)) if p.card_id == furret.card_id])
        == 2
    )

    assert report.prices > 0
    counts = [
        await session.scalar(select(func.count()).select_from(m))
        for m in (CardSet, Card, Printing, CardName, PriceSnapshot)
    ]
    await sync_pokemon(session)
    assert [
        await session.scalar(select(func.count()).select_from(m))
        for m in (CardSet, Card, Printing, CardName, PriceSnapshot)
    ] == counts

    await make_user(session)
    headers = await bearer(client, "alice")
    page = (await client.get("/api/cards", params={"q": "Fouinar"}, headers=headers)).json()
    assert [c["name"] for c in page["items"]] == ["Furret"]
    detail = (await client.get(f"/api/cards/{page['items'][0]['id']}", headers=headers)).json()
    swsh3 = next(p for p in detail["printings"] if p["set"]["code"] == "DAA")
    assert swsh3["names"] == {"en": "Furret", "fr": "Fouinar"}


async def test_price_job_fetches_owned_cards_only(session, tcgdex):
    await sync_pokemon(session)
    user_id = (await make_user(session)).id
    for set_id, local_id in (("swsh3", "136"), ("SV1a", "001")):
        session.add(
            CollectionItem(
                user_id=user_id,
                printing_id=await printing_id(session, set_id, local_id),
                finish="normal",
                language="en",
                quantity=1,
            )
        )
    await session.commit()
    before = len(tcgdex.calls)

    run_id = await jobs.run_job("pokemon", JobKind.prices)
    paths = sorted(call.request.url.path for call in tcgdex.calls[before:])
    assert paths == ["/v2/en/cards/swsh3-136", "/v2/ja/cards/SV1a-001"]
    report = (await session.get(SyncRun, run_id)).report
    assert report["stored"] >= 2
