import importlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import func, select, text

from app.core import progress
from app.core.config import get_settings
from app.core.http import http_client
from app.games.base import OcrLine, get_provider, rarity_of
from app.games.cardmarket import DOWNLOAD_URL as CARDMARKET_URL
from app.games.yugioh import codes, konami, ygojson, ygoprodeck
from app.main import register_games
from app.models import Card, CardName, CardSet, PriceSnapshot, Printing
from app.services.catalog import sync_catalog

yugioh = importlib.import_module("app.games.yugioh.provider")
FIXTURES = Path(__file__).parent / "fixtures"
DATA = json.loads((FIXTURES / "yugioh.json").read_text())
KONAMI_JA = (FIXTURES / "yugioh_konami_ja.html").read_text()
DARK_MAGICIAN = 46986414


def ygojson_zip() -> bytes:
    """YGOJSON's individual.zip holding the fixture's cards and sets."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for card in DATA["ygojson_cards"]:
            archive.writestr(f"cards/{card['id']}.json", json.dumps(card))
        for index, ys in enumerate(DATA["ygojson_sets"]):
            archive.writestr(f"sets/{index}.json", json.dumps(ys))
    return out.getvalue()


def parsed_ygojson(tmp_path: Path) -> ygojson.YgoJson:
    path = tmp_path / "individual.zip"
    path.write_bytes(ygojson_zip())
    return ygojson.parse(path)


def catalog(tmp_path, pages=None):
    names = {"fr": {int(k): v for k, v in DATA["names_fr"].items()}}
    return yugioh.build_catalog(
        DATA["cards"], DATA["sets"], names, parsed_ygojson(tmp_path), pages or {}
    )


def by_card(batch):
    return {c.name: c for c in batch.cards}


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(yugioh, "_cached", None)
    monkeypatch.setattr(get_settings(), "image_dir", tmp_path / "images")


def test_catalog_names_printings_and_prices(tmp_path):
    batch = catalog(tmp_path)
    cards = by_card(batch)
    dm = cards["Dark Magician"]
    assert dm.external_id == str(DARK_MAGICIAN) and dm.colors == ["dark"]
    # French from YGOPRODeck, Asian languages from YGOJSON.
    assert dm.names["fr"] == "Magicien Sombre" and dm.names["ja"] == "ブラック・マジシャン"
    assert dm.names["zh-hans"] == "黑魔导" and dm.attributes["konami_id"] == 4041
    assert cards["Pot of Greed"].colors == ["spell"] and cards["Mirror Force"].colors == ["trap"]
    tcg = {p.external_id: p for p in dm.printings if p.set_external_id != p.collector_number}
    mega = tcg["CT14-EN001~secretrare"]
    assert (mega.set_external_id, mega.collector_number, mega.rarity) == (
        "2017 Mega-Tins",
        "CT14-EN001",
        "Secret Rare",
    )
    # Editions and European languages of the printing from YGOJSON.
    assert mega.finishes == ["limited"] and {"en", "fr", "de"} <= set(mega.languages)
    assert rarity_of("yugioh", mega.rarity).code == "secret"
    # YGOJSON rarity slugs ("starlight", "mosaic") pair with YGOPRODeck's names.
    special = {
        p.collector_number: p
        for c in batch.cards
        for p in c.printings
        if p.rarity in ("Starlight Rare", "Mosaic Rare", "Starfoil Rare")
    }
    assert {"fr", "de", "it"} <= set(special["MP25-EN050"].languages)
    assert {"fr", "de"} <= set(special["BP02-EN129"].languages)
    # Japanese printings in a set of their own.
    sets = {s.external_id: s for s in batch.sets}
    jp = [p for c in batch.cards for p in c.printings if sets[p.set_external_id].lang == "ja"]
    assert jp and all(p.languages == ["ja"] and "-JP" in p.collector_number for p in jp)
    assert sets["2017 Mega-Tins"].code == "CT14" and sets["2017 Mega-Tins"].lang == "en"
    # One code and rarity under two cards: both kept, apart.
    ids = [(p.set_external_id, p.external_id) for c in batch.cards for p in c.printings]
    assert len(ids) == len(set(ids))
    assert sum(1 for _, ext in ids if ext.startswith("BLCR-EN015~secretrare")) == 2
    # OCG card without a password yet: its own card, English name from YGOJSON.
    ocg = next(c for c in batch.cards if c.external_id.startswith("ygojson:"))
    assert ocg.name == "The Twin Kings, Founders of the Empire" and "ja" in ocg.names
    assert ocg.printings[0].rarity == "Extra Secret Rare"
    # TCGplayer prices (USD) from YGOPRODeck.
    usd = [q for q in batch.prices if q.printing_external_id == "CT14-EN001~secretrare"]
    assert usd and {q.source for q in usd} == {"tcgplayer"} and usd[0].currency == "USD"


def test_konami_page_adds_names_and_newer_printings(tmp_path):
    page = konami.parse(KONAMI_JA)
    assert page.name == "ブラック・マジシャン"
    assert [p.number for p in page.packs][:2] == ["YAC1-JP071", "YAC1-JP071"]
    batch = catalog(tmp_path, {4041: {"ja": page}})
    dm = by_card(batch)["Dark Magician"]
    new = {p.external_id: p for p in dm.printings if p.set_external_id == "YAC1-JP"}
    assert set(new) == {"YAC1-JP071~ultrarare", "YAC1-JP071~secretrare"}
    sets = {s.external_id: s for s in batch.sets}
    assert sets["YAC1-JP"].lang == "ja" and sets["YAC1-JP"].name == "ORIGINAL ARTWORK COLLECTION"


async def test_konami_requests_only_missing_pages(session, tmp_path):
    cache = konami.Cache(tmp_path / "konami.json")
    cache.put(1, "ja", konami.Page("名前", fetched_at=datetime.now(UTC).isoformat()))
    with respx.mock() as router:
        route = router.get(url__startswith=konami.URL).respond(text=KONAMI_JA)
        async with http_client() as http:
            read = await konami.fill(http, cache, [(1, "ja"), (4041, "ja")], daily=5)
    assert read == 1 and route.call_count == 1
    assert konami.Cache(tmp_path / "konami.json").get(4041, "ja").name == "ブラック・マジシャン"
    # The day's budget is spent: nothing more is asked.
    with respx.mock(assert_all_called=False) as router:
        route = router.get(url__startswith=konami.URL).respond(text=KONAMI_JA)
        async with http_client() as http:
            assert await konami.fill(http, cache, [(2, "ja")], daily=1) == 0
    assert route.call_count == 0


async def test_konami_unreachable_stops_and_reports_progress(session, tmp_path, monkeypatch):
    """Timeouts never reach the response hook: the loop reports progress itself, gives the
    budget back and stops after a few network errors in a row (no 15-minute stall)."""
    monkeypatch.setattr(konami, "MAX_FAILURES", 2)
    state = progress.Progress(run_id=0, last=0.0)
    token = progress.current.set(state)
    used = text("SELECT coalesce(sum(requests), 0) FROM api_usage WHERE source = 'konami'")
    before = await session.scalar(used)
    try:
        with respx.mock() as router:
            route = router.get(url__startswith=konami.URL).mock(
                side_effect=httpx.ConnectTimeout("handshake timed out")
            )
            async with http_client() as http:
                read = await konami.fill(
                    http, konami.Cache(tmp_path / "k.json"), [(7, "ja"), (8, "ja"), (9, "ja")], 5
                )
    finally:
        progress.current.reset(token)
    assert read == 0 and route.call_count == 2
    assert state.last > 0
    await session.rollback()
    assert await session.scalar(used) == before


def test_codes_without_region():
    assert codes.number_key("LOB-EN001") == codes.number_key("LOB-001") == "LOB-001"
    assert codes.number_key("SDK-E001") == "SDK-001"
    assert codes.number_key("YS15-ENL22") == "YS15-L22"
    assert codes.region_of("BETB-KR024") == "KR" and codes.base_code("BETB-KR024") == "BETB"
    assert codes.rarity_key("PLatinum Secret Rare") == codes.rarity_key("platinumsecret")
    assert codes.rarity_key("Rare") == "rare" and codes.rarity_key("Starlight Rare") == "starlight"


def test_konami_wanted_newest_first(tmp_path):
    wanted = yugioh.konami_wanted(DATA["cards"], parsed_ygojson(tmp_path), ["en", "ja", "ko"])
    # Every fixture card has YGOJSON names: none is asked.
    assert wanted == []
    assert yugioh.konami_wanted(DATA["cards"], None, ["en", "ja"])[0][1] == "ja"


@pytest.fixture
async def router():
    await register_games()
    with respx.mock(assert_all_called=False) as router:
        api = ygoprodeck.API_URL
        router.get(f"{api}/cardinfo.php", params={"misc": "yes"}).respond(
            json={"data": DATA["cards"]}
        )
        for lang in ygoprodeck.LANGUAGES:
            names = DATA["names_fr"] if lang == "fr" else {}
            router.get(f"{api}/cardinfo.php", params={"language": lang}).respond(
                json={"data": [{"id": int(k), "name": v} for k, v in names.items()]}
            )
        router.get(f"{api}/cardsets.php").respond(json=DATA["sets"])
        router.get(ygojson.URL).respond(content=ygojson_zip())
        router.get(url__startswith=konami.URL).respond(text="<html></html>")
        router.get(f"{CARDMARKET_URL}/productList/products_singles_3.json").respond(
            json={"products": DATA["cardmarket_products"]}
        )
        router.get(f"{CARDMARKET_URL}/priceGuide/price_guide_3.json").respond(
            json={"priceGuides": DATA["cardmarket_guides"]}
        )
        yield router


def catalog_batch():
    return yugioh._cached[1]


async def test_sync_catalog_and_prices(session, router):
    async with http_client() as http:
        report = await sync_catalog(session, get_provider("yugioh"), http)
    assert report.printings == sum(len(c.printings) for c in catalog_batch().cards)
    langs = set(
        await session.scalars(select(CardSet.lang).where(CardSet.game_id == "yugioh").distinct())
    )
    assert {"en", "ja"} <= langs
    long_name = await session.scalar(
        select(func.max(func.length(CardSet.external_id))).where(CardSet.game_id == "yugioh")
    )
    assert long_name > 32
    card = await session.scalar(select(Card).where(Card.external_id == str(DARK_MAGICIAN)))
    names = set(await session.scalars(select(CardName.lang).where(CardName.card_id == card.id)))
    assert {"en", "fr", "ja", "ko"} <= names
    sources = set(
        await session.scalars(
            select(PriceSnapshot.source)
            .join(Printing, PriceSnapshot.printing_id == Printing.id)
            .where(Printing.card_id == card.id)
            .distinct()
        )
    )
    assert sources == {"cardmarket", "tcgplayer"}


def test_parse_ocr():
    provider = get_provider("yugioh")
    hints = provider.parse_ocr(
        [
            OcrLine("Dark Magician", 0.08, 0.05),
            OcrLine("LOB-EN005", 0.7, 0.72),
            OcrLine("46986414", 0.05, 0.96),
            OcrLine("©1996 KAZUKI TAKAHASHI", 0.5, 0.97),
        ]
    )
    assert (hints.set_code, hints.collector_number, hints.name, hints.lang) == (
        "LOB",
        "LOB-EN005",
        "Dark Magician",
        "en",
    )
    assert hints.recognized
    # A French printing is stored under its English code.
    fr = provider.parse_ocr(
        [OcrLine("Magicien Sombre", 0.1, 0.05), OcrLine("CT13-FR003", 0.7, 0.7)]
    )
    assert (fr.set_code, fr.collector_number, fr.lang) == ("CT13", "CT13-EN003", "fr")
    jp = provider.parse_ocr(
        [OcrLine("ブラック・マジシャン", 0.1, 0.05), OcrLine("BE1-JP102", 0.7, 0.7)]
    )
    assert (jp.set_code, jp.collector_number, jp.lang) == ("BE1-JP", "BE1-JP102", "ja")
