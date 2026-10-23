import io
import json
import tarfile
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest
import respx
from sqlalchemy import func, select, update

from app.core.http import http_client
from app.games.base import get_provider
from app.games.pokemon import shared
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

API = json.loads((Path(__file__).parent / "fixtures" / "pokemon_api.json").read_text())


@pytest.fixture(autouse=True)
def languages(monkeypatch):
    monkeypatch.setenv("TCG_POKEMON_LANGUAGES", '["en", "fr", "ja", "ko"]')
    # The Korean and Chinese datasets only where a test provides them.
    monkeypatch.setenv("TCG_POKEMON_KOREAN", "false")
    monkeypatch.setenv("TCG_POKEMON_CHINESE", "false")


POKEMON = ("pokemon", "pokemon-asia", "pokemon-china")


def _listings() -> dict:
    """TCGdex's English card list and series, from the English sets of `API`."""
    sets = [v for k, v in API.items() if k.startswith("/en/sets/")]
    return {
        "/en/cards": [c for s in sets for c in s.get("cards", [])],
        "/en/series/tcgp": {
            "id": "tcgp",
            "sets": [{"id": s["id"]} for s in sets if (s.get("serie") or {}).get("id") == "tcgp"],
        },
    }


@pytest.fixture
def tcgdex():
    shared.clear()

    def respond(request: httpx.Request) -> httpx.Response:
        # Like the real server, a literal "+" in the path means a space.
        raw = request.url.raw_path.decode().split("?")[0].replace("+", " ")
        path = unquote(raw).removeprefix("/v2")
        data = API | _listings()
        if path in data:
            return httpx.Response(200, json=data[path])
        return httpx.Response(404, json={"error": "not found"})

    with respx.mock(assert_all_called=False) as router:
        route = router.get(url__startswith=API_URL).mock(side_effect=respond)
        yield route
    shared.clear()


async def sync_pokemon(session, games=POKEMON):
    """Sync the Pokémon games; their reports by game."""
    await register_games()
    reports = {}
    async with http_client() as http:
        for game in games:
            reports[game] = await sync_catalog(session, get_provider(game), http)
    return reports


async def printing_id(session, set_id: str, local_id: str) -> int:
    return await session.scalar(
        select(Printing.id)
        .join(CardSet)
        .where(CardSet.game_id.in_(POKEMON), CardSet.external_id == set_id)
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
    reports = await sync_pokemon(session)
    report = reports["pokemon"]
    sets = {s.external_id: s for s in await session.scalars(select(CardSet))}
    # SM1+ is listed without cards (its id needs URL encoding): fetched, then pruned.
    assert {k: s.game_id for k, s in sets.items()} == {
        "swsh3": "pokemon",
        "hgss1": "pokemon",
        "SV1a": "pokemon-asia",
    }
    assert reports["pokemon-asia"].pruned_sets == 1
    assert sets["swsh3"].code == "DAA" and sets["swsh3"].lang is None
    assert sets["SV1a"].lang == "ja"

    all_cards = list(await session.scalars(select(Card)))
    assert {(c.game_id, c.external_id) for c in all_cards} == {
        ("pokemon", "en:furret"),
        ("pokemon", "en:heatran"),
        ("pokemon", "en:spikemuth"),
        ("pokemon", "fr:dracaufeu v"),
        ("pokemon-asia", "ja:トロピウス"),
        # The Japanese Furret (オオタチ) is keyed on the English name (species names).
        ("pokemon-asia", "en:furret"),
    }
    cards = {c.external_id: c for c in all_cards if c.game_id == "pokemon"}
    cards["ja:トロピウス"] = next(c for c in all_cards if c.external_id == "ja:トロピウス")
    assert cards["en:furret"].colors == ["colorless"]
    # A Trainer: "No type" (Colorless is a type of its own).
    assert cards["en:spikemuth"].colors == ["none"]
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
    # The Japanese Furret is a card of the Asia game.
    furret_printings = [
        p for p in await session.scalars(select(Printing)) if p.card_id == furret.card_id
    ]
    assert len(furret_printings) == 2

    # SV1a is listed in Japanese and Korean: one Japanese set, Korean adds names and images.
    tropius = await session.get(Printing, await printing_id(session, "SV1a", "001"))
    assert tropius.card_id == cards["ja:トロピウス"].id
    assert tropius.languages == ["ja", "ko"]
    assert set(tropius.image_urls) == {"ja", "ko"}
    assert tropius.attributes["attacks"][0]["name"] == "リーフドレイン"
    assert sets["SV1a"].name == "トリプレットビート"
    japanese_furret = await session.get(Printing, await printing_id(session, "SV1a", "002"))
    asian_furret = next(
        c for c in all_cards if c.game_id == "pokemon-asia" and "furret" in c.external_id
    )
    assert japanese_furret.card_id == asian_furret.id
    assert set(japanese_furret.image_urls) == {"ja"}

    assert report.prices > 0 and reports["pokemon-asia"].prices > 0
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

    async def search(query, game):
        params = {"q": query, "game": game}
        return (await client.get("/api/cards", params=params, headers=headers)).json()["items"]

    page = await search("Fouinar", "pokemon")
    assert [c["name"] for c in page] == ["Furret"]
    detail = (await client.get(f"/api/cards/{page[0]['id']}", headers=headers)).json()
    swsh3 = next(p for p in detail["printings"] if p["set"]["code"] == "DAA")
    assert swsh3["names"]["fr"] == "Fouinar"
    assert swsh3["names"]["ja"] == "オオタチ"
    # Japanese printings are the Asia game's.
    assert {p["set"]["code"] for p in detail["printings"]} == {"DAA", "HS"}
    asian = await search("Furret", "pokemon-asia")
    assert [(c["name"], c["translation"]) for c in asian] == [("オオタチ", "Furret")]
    detail = (await client.get(f"/api/cards/{asian[0]['id']}", headers=headers)).json()
    sv1a = next(p for p in detail["printings"] if p["set"]["code"] == "SV1a")
    assert sv1a["names"]["ja"] == "オオタチ" and sv1a["names"]["ko"] == "다꼬리"

    # Names in every language: species names give the ones TCGdex does not.
    for query in ("オオタチ", "Wiesenior"):
        assert [c["name"] for c in await search(query, "pokemon")] == ["Furret"], query
    # Printed only in Japanese: the Japanese name, translated in the interface language
    # (English here).
    page = await search("トロピウス", "pokemon-asia")
    assert [(c["name"], c["translation"]) for c in page] == [("トロピウス", "Tropius")]
    furret = await search("Furret", "pokemon")
    assert [(c["name"], c["translation"]) for c in furret] == [("Furret", None)]
    detail = (await client.get(f"/api/cards/{furret[0]['id']}", headers=headers)).json()
    assert detail["default_printing_id"] == furret[0]["printing_id"]


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
    for game, path in (
        ("pokemon", "/v2/en/cards/swsh3-136"),
        ("pokemon-asia", "/v2/ja/cards/SV1a-001"),
    ):
        before = len(tcgdex.calls)
        run_id = await jobs.run_job(game, JobKind.prices)
        assert [call.request.url.path for call in tcgdex.calls[before:]] == [path]
        report = (await session.get(SyncRun, run_id)).report
        assert report["stored"] >= 1


async def test_card_names_follow_interface_language(client, session, tcgdex):
    await sync_pokemon(session)
    await make_user(session)
    headers = await bearer(client, "alice")
    response = await client.patch("/api/auth/me", json={"language": "fr"}, headers=headers)
    assert response.status_code == 200, response.text
    params = {"q": "furret", "game": "pokemon"}
    page = (await client.get("/api/cards", params=params, headers=headers)).json()
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
    for set_id, local_id, lang in (("swsh3", "136", "en"), ("SV1a", "001", "ja")):
        body = {
            "printing_id": await printing_id(session, set_id, local_id),
            "finish": "normal",
            "language": lang,
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

    async def names(lang, game="pokemon"):
        params = {"game": game, "lang": lang}
        page = (await client.get("/api/cards", params=params, headers=headers)).json()
        return {c["name"] for c in page["items"]}

    assert "Furret" in await names("fr")
    assert "Tropius" not in await names("fr")
    assert await names("ja") == set()
    assert {"オオタチ", "トロピウス"} <= await names("ja", "pokemon-asia")


async def test_refresh_fetches_printings_again(session, tcgdex):
    await sync_pokemon(session)
    furret = await printing_id(session, "swsh3", "136")
    ropiusu = await printing_id(session, "SV1a", "001")
    await session.execute(
        update(Printing).where(Printing.id.in_([furret, ropiusu])).values(image_urls={})
    )
    await session.commit()
    cards = {}
    for game, printing in (("pokemon", furret), ("pokemon-asia", ropiusu)):
        cards[game] = (await session.get(Printing, printing)).card_id
    async with http_client() as http:
        for game, card_id in cards.items():
            report = await refresh_cards(session, get_provider(game), http, [card_id])
            assert report.updated == 1 and report.not_found == 0
    session.expire_all()
    assert (await session.get(Printing, furret)).image_urls["en"].startswith("https://")
    # A Japanese printing joined to another card stays on that card.
    japanese = await session.get(Printing, ropiusu)
    assert japanese.image_urls["ja"] and japanese.card_id == cards["pokemon-asia"]


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
    _neo2(monkeypatch)
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
    # Japanese Smeargle is keyed on the English card's name.
    assert (await session.get(Card, unown.card_id)).name == "アンノーンA"
    ja_card = await session.get(Card, smeargle_ja.card_id)
    en_card = await session.get(Card, smeargle_en.card_id)
    assert (ja_card.game_id, en_card.game_id) == ("pokemon-asia", "pokemon")
    assert ja_card.external_id == en_card.external_id == "en:smeargle"
    assert "ドーブル" in set(
        await session.scalars(select(CardName.name).where(CardName.printing_id == smeargle_ja.id))
    )


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


def korean_archive(cards: dict[str, dict]) -> bytes:
    """The Korean dataset's repository archive with these `data_ko/...` files."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path, card in cards.items():
            data = json.dumps(card, ensure_ascii=False).encode()
            info = tarfile.TarInfo(f"PTCG-database-main/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        readme = tarfile.TarInfo("PTCG-database-main/data_jp/x.json")
        readme.size = 2
        tar.addfile(readme, io.BytesIO(b"{}"))
    return buffer.getvalue()


def ko_card(set_name: str, number: str, name: str, **extra) -> dict:
    return {
        "name": name,
        "img": f"https://cards.image.pokemonkorea.co.kr/data/{set_name}_{number}.png",
        "card_type": "Pokémon",
        "ko_id": f"K{set_name}{number}",
        "set_name": set_name,
        "set_full_name": f"{set_name} 확장팩",
        "set_img": f"https://cards.image.pokemonkorea.co.kr/symbol/{set_name}.png",
        "number": number,
        "set_total": "080",
        "author": ["Artist"],
        "rarity": "C",
        "stage": "기본",
        "hp": 60,
        "types_en": ["Lightning"],
        **extra,
    }


def chs_card(number: str, name: str, rarity: str = "C", **details) -> dict:
    return {
        "name": name,
        "image": f"img/246/{number}{rarity.count('★')}.png",
        "details": {
            "cardName": name,
            "collectionNumber": f"{number}/151",
            "rarityText": rarity,
            "cardTypeText": "宝可梦",
            "evolveText": "基础",
            "hp": 60,
            "attribute": "4",
            "illustratorName": ["Someone"],
            **details,
        },
    }


async def test_korean_and_chinese_datasets(client, session, tcgdex, monkeypatch):
    from app.games.pokemon.asia import CHINESE_DATA, KOREAN_ARCHIVE

    monkeypatch.setenv("TCG_POKEMON_LANGUAGES", '["en", "ja"]')
    monkeypatch.setenv("TCG_POKEMON_KOREAN", "true")
    monkeypatch.setenv("TCG_POKEMON_CHINESE", "true")
    archive = korean_archive(
        {
            # Same set id as the Japanese SV1a: names and images on its printings.
            "data_ko/SV1a/001.json": ko_card("SV1a", "001", "트로피우스", types_en=["Grass"]),
            # Not in TCGdex's Japanese set: added in full.
            "data_ko/SV1a/050.json": ko_card("SV1a", "050", "피카츄", pokedex_number=25),
            # A Korean-only set, a trainer, and a number another card already uses.
            "data_ko/M2/001.json": ko_card("M2", "001", "뚜벅쵸", pokedex_number=43),
            "data_ko/M2/002.json": ko_card(
                "M2", "002", "박사의 연구", card_type="서포트", hp=None, stage=None, types_en=[]
            ),
            "data_ko/M2/002b.json": ko_card("M2", "002", "다른 카드"),
            "data_ko/no_set/x.json": {"name": "기본 에너지", "card_type": "기본 에너지"},
        }
    )
    chinese = {
        "collections": [
            {
                "commodityCode": "151C",
                "name": "收集啦151 活动包",
                "salesDate": "2025-01-17",
                "cards": [
                    chs_card("025", "皮卡丘"),
                    chs_card("025", "皮卡丘", "C★"),
                    # Another card with the same number in this box.
                    chs_card("025", "木木枭"),
                    chs_card(
                        "100",
                        "能量输送",
                        "无标记",
                        cardTypeText="训练家",
                        evolveText=None,
                        hp=None,
                        attribute=None,
                        trainerTypeText="物品",
                    ),
                ],
            },
            {"commodityCode": "EMPTY", "name": "Nothing", "cards": []},
        ]
    }
    with respx.mock(assert_all_called=False) as router:
        router.get(url__startswith=API_URL).mock(side_effect=tcgdex.side_effect)
        router.get(KOREAN_ARCHIVE).respond(content=archive)
        router.get(CHINESE_DATA).respond(json=chinese)
        reports = await sync_pokemon(session)

    sets = {s.external_id: s for s in await session.scalars(select(CardSet))}
    assert {"SV1a", "M2", "151C"} <= set(sets)
    assert (sets["M2"].game_id, sets["151C"].game_id) == ("pokemon-asia", "pokemon-china")
    assert "EMPTY" not in sets and reports["pokemon-china"].pruned_sets >= 1
    assert (sets["M2"].lang, sets["M2"].name, sets["M2"].total) == ("ko", "M2 확장팩", 80)
    assert (sets["151C"].lang, str(sets["151C"].release_date)) == ("zh-hans", "2025-01-17")

    tropius = await session.get(Printing, await printing_id(session, "SV1a", "001"))
    assert tropius.languages == ["ja", "ko"]
    assert tropius.image_urls["ko"].endswith("SV1a_001.png")
    korean_pikachu = await session.get(Printing, await printing_id(session, "SV1a", "050"))
    assert korean_pikachu.languages == ["ko"]
    m2 = {
        p.external_id: p
        for p in await session.scalars(select(Printing).where(Printing.set_id == sets["M2"].id))
    }
    assert set(m2) == {"001", "002", "002~KM2002"}
    oddish = await session.get(Card, m2["001"].card_id)
    assert oddish.attributes == {"category": "Pokemon", "hp": 60, "stage": "Basic", "dexId": [43]}
    research = await session.get(Card, m2["002"].card_id)
    assert research.attributes == {"category": "Trainer", "trainerType": "Supporter"}

    chinese_pikachu = await session.scalar(
        select(Printing).where(Printing.set_id == sets["151C"].id, Printing.external_id == "025")
    )
    assert chinese_pikachu.finishes == ["normal", "reverse"]
    rowlet = await session.scalar(
        select(Printing).where(Printing.set_id == sets["151C"].id, Printing.external_id == "025~2")
    )
    assert rowlet.collector_number == "025" and rowlet.card_id != chinese_pikachu.card_id
    assert chinese_pikachu.rarity == "C"
    assert chinese_pikachu.image_urls == {
        "zh-hans": "https://raw.githubusercontent.com/duanxr/PTCG-CHS-Datasets/main/img/246/0250.png"
    }
    # Named after the species in every language (they would join an English Pikachu).
    pikachu = await session.get(Card, chinese_pikachu.card_id)
    assert pikachu.colors == ["lightning"]
    names = set(await session.scalars(select(CardName.name).where(CardName.card_id == pikachu.id)))
    assert {"皮卡丘", "Pikachu", "ピカチュウ", "피카츄"} <= names


def test_long_artist_lists_fit():
    from app.games.pokemon.asia import artists

    long = artists([f"Illustrator number {i}" for i in range(30)])
    assert len(long) <= 255 and long.endswith("…")
    assert artists(["A", " B "]) == "A, B" and artists([]) is None
