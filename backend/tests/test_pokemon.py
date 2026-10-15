import json
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest
import respx
from sqlalchemy import func, select, update

from app.core.http import http_client
from app.games.base import get_provider
from app.games.pokemon.pokemontcg import DATA_URL as POKEMONTCG_URL
from app.games.pokemon.provider import API_URL, parse_card, parse_prices
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
from app.services.refresh import refresh_cards
from tests.conftest import bearer, make_user

POKEMONTCG: dict[str, object] = {}
API = json.loads((Path(__file__).parent / "fixtures" / "pokemon_api.json").read_text())


@pytest.fixture(autouse=True)
def languages(monkeypatch):
    monkeypatch.setenv("TCG_POKEMON_LANGUAGES", '["en", "fr", "ja", "ko"]')


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
        # Second source (pokemontcg data files): nothing unless a test adds files.
        router.get(url__startswith=POKEMONTCG_URL).mock(
            side_effect=lambda request: (
                httpx.Response(200, json=POKEMONTCG[str(request.url).removeprefix(POKEMONTCG_URL)])
                if str(request.url).removeprefix(POKEMONTCG_URL) in POKEMONTCG
                else httpx.Response(404)
            )
        )
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
    assert furret.image_urls == {
        "en": "https://assets.tcgdex.net/en/swsh/swsh3/136/high.webp",
        "fr": "https://assets.tcgdex.net/fr/swsh/swsh3/136/high.webp",
    }
    assert furret.rarity == "Uncommon"  # translation did not clear details
    # The Japanese Furret (オオタチ) joined the English card through species names.
    furret_printings = [
        p for p in await session.scalars(select(Printing)) if p.card_id == furret.card_id
    ]
    assert len(furret_printings) == 3

    # SV1a is listed in Japanese and Korean: one Japanese set, Korean adds names and images.
    tropius = await session.get(Printing, await printing_id(session, "SV1a", "001"))
    assert tropius.card_id == cards["ja:トロピウス"].id
    assert tropius.languages == ["ja", "ko"]
    assert set(tropius.image_urls) == {"ja", "ko"}
    assert tropius.attributes["attacks"][0]["name"] == "リーフドレイン"
    assert sets["SV1a"].name == "トリプレットビート"
    japanese_furret = await session.get(Printing, await printing_id(session, "SV1a", "002"))
    assert japanese_furret.card_id == furret.card_id
    assert set(japanese_furret.image_urls) == {"ja"}

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
    assert swsh3["names"]["fr"] == "Fouinar"
    assert swsh3["names"]["ja"] == "オオタチ"
    sv1a = next(p for p in detail["printings"] if p["set"]["code"] == "SV1a")
    assert sv1a["names"]["ja"] == "オオタチ" and sv1a["names"]["ko"] == "다꼬리"

    # Names in every language: species names give the ones TCGdex does not.
    for query in ("オオタチ", "Wiesenior"):
        page = (await client.get("/api/cards", params={"q": query}, headers=headers)).json()
        assert [c["name"] for c in page["items"]] == ["Furret"], query
    # Printed only in Japanese: the Japanese name, translated in the interface language
    # (English here).
    page = (await client.get("/api/cards", params={"q": "トロピウス"}, headers=headers)).json()
    assert [(c["name"], c["translation"]) for c in page["items"]] == [("トロピウス", "Tropius")]
    # Furret is also printed in Latin sets: shown in the interface language.
    furret = (await client.get("/api/cards", params={"q": "Furret"}, headers=headers)).json()
    assert [(c["name"], c["translation"]) for c in furret["items"]] == [("Furret", None)]
    detail = (await client.get(f"/api/cards/{furret['items'][0]['id']}", headers=headers)).json()
    shown = {p["set"]["code"]: (p["name"], p["translation"]) for p in detail["printings"]}
    # Each printing is named as printed in its own set.
    assert shown["DAA"] == ("Furret", None) and shown["SV1a"] == ("オオタチ", "Furret")
    assert detail["default_printing_id"] == furret["items"][0]["printing_id"]


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


async def test_card_names_follow_interface_language(client, session, tcgdex):
    await sync_pokemon(session)
    await make_user(session)
    headers = await bearer(client, "alice")
    response = await client.patch("/api/auth/me", json={"language": "fr"}, headers=headers)
    assert response.status_code == 200, response.text
    page = (await client.get("/api/cards", params={"q": "furret"}, headers=headers)).json()
    assert [c["name"] for c in page["items"]] == ["Fouinar"]
    detail = (await client.get(f"/api/cards/{page['items'][0]['id']}", headers=headers)).json()
    assert detail["name"] == "Fouinar"


async def test_search_by_set_code_and_number(client, session, tcgdex):
    await sync_pokemon(session)
    await make_user(session)
    headers = await bearer(client, "alice")
    for query in ("pkm daa 136", "DAA 136/189", "pokemon swsh3 136", "pkm furret"):
        page = (await client.get("/api/cards", params={"q": query}, headers=headers)).json()
        assert [c["name"] for c in page["items"]] == ["Furret"], query


async def test_collection_names_as_printed(client, session, tcgdex):
    await sync_pokemon(session)
    await make_user(session)
    headers = await bearer(client, "alice")
    for set_id, local_id in (("swsh3", "136"), ("SV1a", "001")):
        body = {
            "printing_id": await printing_id(session, set_id, local_id),
            "finish": "normal",
            "language": "en",
            "delta": 1,
        }
        response = await client.post("/api/collection/adjust", json=body, headers=headers)
        assert response.status_code == 200, response.text

    # Each copy is named as printed in its set: Japanese printings with a translation.
    items = (await client.get("/api/collection", headers=headers)).json()["items"]
    assert sorted((i["name"], i["translation"]) for i in items) == [
        ("Furret", None),
        ("トロピウス", "Tropius"),
    ]
    tropius = next(i for i in items if i["translation"])
    assert tropius["image"].endswith("?lang=ja")
    moves = (await client.get("/api/collection/transactions", headers=headers)).json()
    assert sorted((t["name"], t["translation"]) for t in moves) == [
        ("Furret", None),
        ("トロピウス", "Tropius"),
    ]


async def test_search_by_printed_language(client, session, tcgdex):
    await sync_pokemon(session)
    await make_user(session)
    headers = await bearer(client, "alice")

    async def names(lang):
        params = {"game": "pokemon", "lang": lang}
        page = (await client.get("/api/cards", params=params, headers=headers)).json()
        return {c["name"] for c in page["items"]}

    assert "Furret" in await names("fr")
    assert "Tropius" not in await names("fr")
    assert {"Furret", "トロピウス"} <= await names("ja")


async def test_refresh_fetches_printings_again(session, tcgdex):
    await sync_pokemon(session)
    furret = await printing_id(session, "swsh3", "136")
    ropiusu = await printing_id(session, "SV1a", "001")
    await session.execute(
        update(Printing).where(Printing.id.in_([furret, ropiusu])).values(image_urls={})
    )
    await session.commit()
    card_ids = list(
        await session.scalars(
            select(Printing.card_id).where(Printing.id.in_([furret, ropiusu])).distinct()
        )
    )
    async with http_client() as http:
        report = await refresh_cards(session, get_provider("pokemon"), http, card_ids)
    assert report.updated == len(card_ids) and report.not_found == 0
    session.expire_all()
    assert (await session.get(Printing, furret)).image_urls["en"].startswith("https://")
    # A Japanese printing joined to an English card stays on that card.
    japanese = await session.get(Printing, ropiusu)
    assert japanese.image_urls["ja"] and japanese.card_id in card_ids


def test_tcgplayer_prices_and_product_ids():
    raw = {
        "localId": "136",
        "variants": {"normal": True, "reverse": True},
        "pricing": {
            "tcgplayer": {
                "unit": "USD",
                "normal": {"productId": 219333, "lowPrice": 0.02, "midPrice": 0.25,
                           "marketPrice": 0.26},
                "reverse-holofoil": {"productId": 219333, "lowPrice": 0.17, "midPrice": 0.43,
                                     "marketPrice": None},
            }
        },
    }  # fmt: skip
    quotes = {(q.source, q.finish): q for q in parse_prices(raw, "swsh3")}
    assert set(quotes) == {("tcgplayer", "normal"), ("tcgplayer", "reverse")}
    assert quotes["tcgplayer", "normal"].trend == Decimal("0.26")
    assert quotes["tcgplayer", "reverse"].trend == Decimal("0.43")  # mid when no market
    assert quotes["tcgplayer", "normal"].currency == "USD"
    card = parse_card(raw | {"name": "Furret", "category": "Pokemon"}, "swsh3", "en")
    assert card.printings[0].attributes["market_ids"] == {"tcgplayer": 219333}


async def test_pokemontcg_fills_images_and_checks(session, tcgdex, monkeypatch):
    from app.services.crosscheck import cross_check

    monkeypatch.setitem(
        POKEMONTCG,
        "/sets/en.json",
        [
            {"id": "swsh3", "name": "Darkness Ablaze", "ptcgoCode": "DAA",
             "releaseDate": "2020/08/14", "total": 201},
            {"id": "zzz", "name": "Not ours", "releaseDate": "2000/01/01", "total": 1},
        ],
    )  # fmt: skip
    image = "https://images.pokemontcg.io/swsh3/136_hires.png"
    monkeypatch.setitem(
        POKEMONTCG,
        "/cards/en/swsh3.json",
        [
            {"number": "136", "name": "Furret", "rarity": "Rare", "artist": "tetsuya koizumi",
             "images": {"large": image}},
            {"number": "025", "name": "Heatran", "rarity": None},
        ],
    )  # fmt: skip
    await sync_pokemon(session)
    furret = await printing_id(session, "swsh3", "136")
    await session.execute(update(Printing).where(Printing.id == furret).values(image_urls={}))
    await session.commit()
    async with http_client() as http:
        report = await cross_check(session, get_provider("pokemon"), http)
    assert report.matched == 2 and not report.failed_sources
    assert report.discrepancies == 1  # Furret's rarity
    session.expire_all()
    assert (await session.get(Printing, furret)).image_urls == {"en": image}


def _neo2(monkeypatch):
    """Neo Discovery (English) and the Japanese "neo2", another set with the same id."""
    symbol = "https://assets.tcgdex.net/univ/neo/neo2/symbol"
    en_set = {"id": "neo2", "name": "Neo Discovery", "symbol": symbol,
              "cardCount": {"total": 75, "official": 75}, "serie": {"id": "neo"},
              "cards": [{"id": "neo2-30", "localId": "30", "name": "Smeargle",
                         "image": "https://assets.tcgdex.net/en/neo/neo2/30"}]}  # fmt: skip
    ja_set = {"id": "neo2", "name": "遺跡をこえて", "symbol": symbol,
              "cardCount": {"total": 57, "official": 56}, "serie": {"id": "neo"},
              "cards": [{"id": "neo2-030", "localId": "030", "name": "a"},
                        {"id": "neo2-052", "localId": "052", "name": "Smeargle"}]}  # fmt: skip

    def card(set_raw, local_id, name, dex, lang_image=None):
        return {"category": "Pokemon", "id": f"neo2-{local_id}", "localId": local_id,
                "name": name, "dexId": [dex], "types": ["Colorless"], "stage": "Basic",
                "variants": {"normal": True}, "set": {"id": "neo2"},
                **({"image": lang_image} if lang_image else {})}  # fmt: skip

    entries = {
        "/en/sets": API["/en/sets"] + [{"id": "neo2", "name": "Neo Discovery"}],
        "/en/sets/neo2": en_set,
        "/en/cards/neo2-30": card(en_set, "30", "Smeargle", 235, en_set["cards"][0]["image"]),
        "/ja/sets": API["/ja/sets"] + [{"id": "neo2", "name": "遺跡をこえて"}],
        "/ja/sets/neo2": ja_set,
        "/ja/cards/neo2-030": card(ja_set, "030", "a", 201),
        "/ja/cards/neo2-052": card(ja_set, "052", "Smeargle", 235),
    }
    for path, value in entries.items():
        monkeypatch.setitem(API, path, value)


async def test_asian_set_reusing_an_international_id(session, tcgdex, monkeypatch):
    from app.services.crosscheck import cross_check

    _neo2(monkeypatch)
    monkeypatch.setitem(
        POKEMONTCG, "/sets/en.json",
        [{"id": "neo2", "name": "Neo Discovery", "releaseDate": "2001/06/01", "total": 75}],
    )  # fmt: skip
    english_image = "https://images.pokemontcg.io/neo2/30_hires.png"
    monkeypatch.setitem(
        POKEMONTCG, "/cards/en/neo2.json",
        [{"number": "30", "name": "Smeargle", "images": {"large": english_image}}],
    )  # fmt: skip
    await sync_pokemon(session)
    sets = {s.external_id: s for s in await session.scalars(select(CardSet))}
    assert sets["neo2"].name == "Neo Discovery" and sets["neo2"].lang is None
    assert sets["asia:neo2"].name == "遺跡をこえて" and sets["asia:neo2"].lang == "ja"
    # Symbols come from the English asset path ("univ" is refused); not for the
    # Japanese set, whose listed symbol is Neo Discovery's.
    assert sets["neo2"].icon_url == "https://assets.tcgdex.net/en/neo/neo2/symbol.png"
    assert sets["asia:neo2"].icon_url is None

    unown = await session.get(Printing, await printing_id(session, "asia:neo2", "030"))
    smeargle_ja = await session.get(Printing, await printing_id(session, "asia:neo2", "052"))
    smeargle_en = await session.get(Printing, await printing_id(session, "neo2", "30"))
    # TCGdex names "a" and "Smeargle" written in Japanese from the Pokédex number; the
    # Japanese Smeargle joins the English card.
    assert (await session.get(Card, unown.card_id)).name == "アンノーンA"
    assert smeargle_ja.card_id == smeargle_en.card_id
    assert "ドーブル" in set(
        await session.scalars(select(CardName.name).where(CardName.printing_id == smeargle_ja.id))
    )

    english_id, unown_id = smeargle_en.id, unown.id
    await session.execute(update(Printing).values(image_urls={}))
    await session.commit()
    async with http_client() as http:
        await cross_check(session, get_provider("pokemon"), http)
    session.expire_all()
    # The English image goes to English #30 only, never to Japanese "030".
    assert (await session.get(Printing, english_id)).image_urls == {"en": english_image}
    assert (await session.get(Printing, unown_id)).image_urls == {}


async def test_changed_image_url_and_name_replace_stored_ones(session, tcgdex):
    await sync_pokemon(session)
    furret = await printing_id(session, "swsh3", "136")
    await session.execute(
        update(Printing)
        .where(Printing.id == furret)
        .values(
            image_urls={"en": "https://old.example/136.webp", "fr": API_URL},
            image_paths={"en": "pokemon/1/old-en.webp", "fr": "pokemon/1/fr.webp", "de": ""},
        )
    )
    card_id = (await session.get(Printing, furret)).card_id
    session.add(CardName(card_id=card_id, printing_id=None, lang="de", name="Furet"))
    await session.commit()
    await sync_pokemon(session)
    session.expire_all()
    printing = await session.get(Printing, furret)
    # Both URLs changed: their cached files are forgotten; the refused download in a
    # language without URL is kept.
    assert printing.image_paths == {"de": ""}
    # A name corrected at the source replaces the stored one.
    names = set(
        await session.scalars(
            select(CardName.name).where(
                CardName.card_id == card_id, CardName.printing_id.is_(None), CardName.lang == "de"
            )
        )
    )
    assert names == {"Wiesenior"}
