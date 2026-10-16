import importlib
import json
from pathlib import Path

import pytest
import respx
from sqlalchemy import func, select

from app.core.http import http_client
from app.games.base import OcrLine, get_provider
from app.games.cardmarket import DOWNLOAD_URL as CARDMARKET_URL
from app.games.riftbound import gallery, riftcodex, riot
from app.main import register_games
from app.models import CardSet, CatalogDiscrepancy, PriceSnapshot, Printing
from app.services import prices
from app.services.catalog import sync_catalog
from app.services.crosscheck import cross_check
from app.sources import tcgcsv

# The module (the package's `provider` name is the provider object).
riftbound = importlib.import_module("app.games.riftbound.provider")
FIXTURES = Path(__file__).parent / "fixtures"
DATA = json.loads((FIXTURES / "riftbound.json").read_text())
GALLERY_EN = (FIXTURES / "riftbound_gallery_en.html").read_text()
GALLERY_ZH = (FIXTURES / "riftbound_gallery_zh.html").read_text()


def catalog():
    return riftbound.build_catalog(
        riftcodex.parse_cards(DATA["riftcodex_cards"]),
        gallery.parse_cards(gallery.items(GALLERY_EN)),
        gallery.chinese(gallery.items(GALLERY_ZH)),
        DATA["riftcodex_sets"],
    )


def printings(batch):
    return {p.external_id: (card, p) for card in batch.cards for p in card.printings}


@pytest.fixture(autouse=True)
def fresh_catalog(monkeypatch):
    monkeypatch.setattr(riftbound, "_cached", None)
    monkeypatch.delenv("TCG_APITOKEN_GAMES_RFB_RIOT", raising=False)


@pytest.fixture
async def router():
    await register_games()
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{riftcodex.API_URL}/sets").respond(
            json={"items": DATA["riftcodex_sets"], "pages": 1}
        )
        router.get(f"{riftcodex.API_URL}/cards").respond(
            json={"items": DATA["riftcodex_cards"], "pages": 1, "total": 10}
        )
        router.get(gallery.GALLERY_URL.format(locale="en-us")).respond(text=GALLERY_EN)
        router.get(gallery.GALLERY_URL.format(locale="zh-cn")).respond(text=GALLERY_ZH)
        router.get(f"{CARDMARKET_URL}/productList/products_singles_22.json").respond(
            json={"products": DATA["cardmarket_products"]}
        )
        router.get(f"{CARDMARKET_URL}/priceGuide/price_guide_22.json").respond(
            json={"priceGuides": DATA["cardmarket_guides"]}
        )
        router.get(f"{tcgcsv.BASE_URL}/89/groups").respond(json={"results": DATA["tcgcsv_groups"]})
        router.get(f"{tcgcsv.BASE_URL}/89/24344/products").respond(
            json={"results": DATA["tcgcsv_products"]}
        )
        router.get(f"{tcgcsv.BASE_URL}/89/24344/prices").respond(
            json={"results": DATA["tcgcsv_prices"]}
        )
        router.get(url__regex=rf"{tcgcsv.BASE_URL}/89/\d+/(products|prices)").respond(
            json={"results": []}
        )
        yield router


def test_catalog_from_riftcodex_and_gallery():
    batch = catalog()
    found = printings(batch)
    ahri = next(c for c in batch.cards if c.name == "Ahri, Alluring")
    assert {p.external_id for p in ahri.printings} == {"ogn-066-298", "ogn-066a-298", "pr-066-298"}
    _, alt = found["ogn-066a-298"]
    assert alt.attributes["variant"] == "Alternate Art" and alt.collector_number == "066a"
    assert alt.attributes["market_ids"] == {"tcgplayer": "652843"}
    assert alt.finishes == ["foil"]  # showcase
    _, scorcher = found["ogn-001-298"]
    assert scorcher.finishes == ["normal", "foil"]  # common
    assert scorcher.names == {"zh-hans": "灼焰飞龙"} and "zh-hans" in scorcher.images
    assert scorcher.languages == ["en", "zh-hans"]
    # Gallery ids "ogn-299-star-298" are Riftcodex's "ogn-299*-298": one printing.
    assert "ogn-299*-298" in found and found["ogn-299*-298"][1].collector_number == "299*"
    # Radiance is only in the official gallery.
    card, radiance = found["rad-001-167"]
    assert radiance.set_external_id == "RAD" and radiance.images["en"].startswith(
        "https://cmsassets.rgpub.io/"
    )
    # A Metal print sharing its id with the plain one; a card listed twice is one.
    assert {"opp-249-298", "opp-249-298~metal"} <= set(found)
    assert found["opp-249-298~metal"][1].attributes["variant"] == "Metal"
    assert sum(1 for k in found if k.startswith("ven-164-166")) == 1
    assert found["ven-164-166"][1].attributes["market_ids"] == {"tcgplayer": "706097"}
    sets = {s.code: s for s in batch.sets}
    assert sets["OGN"].name == "Origins" and sets["OGN"].total == 352
    assert sets["RAD"].name == "Radiance"
    assert riftcodex.cardmarket_expansions(DATA["riftcodex_sets"])[6286] == ["OGN"]


def test_names_and_ids():
    from app.games.riftbound.records import split_variant

    assert split_variant("Ahri - Alluring (Alternate Art)") == ("Ahri, Alluring", "Alternate Art")
    assert split_variant("Rek'sai - Void Burrower") == ("Rek'sai, Void Burrower", None)
    assert split_variant("Fury Rune") == ("Fury Rune", None)


def test_rules_text_spells_out_symbols():
    from app.games.riftbound.records import rules_text

    rich = "<p>:rb_energy_2::rb_rune_chaos:, :rb_exhaust:: Kill this.<br />3 :rb_might:</p>"
    assert rules_text(rich) == "2 Chaos, [Exhaust]: Kill this.\n3 Might"


def test_riot_content_is_parsed():
    content = {
        "game": "riftbound",
        "sets": [
            {
                "id": "OGN",
                "name": "Origins",
                "cards": [
                    {
                        "id": "ogn-066-298",
                        "collectorNumber": 66,
                        "set": "OGN",
                        "name": "Ahri",
                        "subtitle": "Alluring",
                        "description": "<p>When I hold, you score 1 point.</p>",
                        "type": "Unit",
                        "rarity": "Rare",
                        "faction": "Calm",
                        "stats": {"energy": 5, "might": 4, "power": 1},
                        "art": {"fullURL": "https://cmsassets.rgpub.io/x.png", "artist": "W"},
                        "tags": ["Ahri"],
                    }
                ],
            }
        ],
    }
    (card,) = riot.parse_content(content)
    assert (card.id, card.name, card.domains, card.might) == (
        "ogn-066-298",
        "Ahri, Alluring",
        ["calm"],
        4,
    )
    assert card.text == "When I hold, you score 1 point."


async def test_sync_prices_and_riot_fallback(session, router, monkeypatch):
    # A Riot key Riot refuses (development key): Riftcodex takes over.
    monkeypatch.setenv("TCG_APITOKEN_GAMES_RFB_RIOT", "test-key")
    refused = router.get(url__startswith="https://europe.api.riotgames.com/").respond(403)
    async with http_client() as http:
        report = await sync_catalog(session, get_provider("riftbound"), http)
    assert refused.call_count == 1
    assert report.printings == len(printings(catalog()))
    count = await session.scalar(
        select(func.count(Printing.id))
        .join(CardSet)
        .where(CardSet.game_id == "riftbound", CardSet.code == "RAD")
    )
    assert count == 1
    # Cardmarket prices matched by name: plain and alternate art Ahri differ.
    rows = dict(
        (await session.execute(
            select(Printing.external_id, PriceSnapshot.trend)
            .join(Printing, PriceSnapshot.printing_id == Printing.id)
            .where(PriceSnapshot.source == "cardmarket", PriceSnapshot.finish == "foil",
                   Printing.external_id.in_(["ogn-066-298", "ogn-066a-298"]))
        )).all()
    )  # fmt: skip
    assert len(rows) == 2 and rows["ogn-066-298"] != rows["ogn-066a-298"]


def test_parse_ocr():
    hints = get_provider("riftbound").parse_ocr(
        [
            OcrLine("Ahri", 0.1, 0.05),
            OcrLine("Alluring", 0.1, 0.1),
            OcrLine("When I hold, you score 1 point.", 0.1, 0.6),
            OcrLine("OGN • 066a/298", 0.05, 0.95),
            OcrLine("© 2025 Riot Games", 0.5, 0.97),
        ]
    )
    assert (hints.set_code, hints.collector_number, hints.name) == ("OGN", "066a", "Ahri")
    assert hints.recognized and hints.lang == "en"
    zh = get_provider("riftbound").parse_ocr([OcrLine("灼焰飞龙", 0.1, 0.05)])
    assert zh.name == "灼焰飞龙" and zh.lang == "zh-hans"


@pytest.mark.gap_sources
async def test_tcgcsv_confirms_finishes_checks_text_and_prices(session, router):
    async with http_client() as http:
        await sync_catalog(session, get_provider("riftbound"), http)
        report = await cross_check(session, get_provider("riftbound"), http)
    assert "tcgcsv" not in report.failed_sources
    scorcher = await session.scalar(select(Printing).where(Printing.external_id == "ogn-001-298"))
    # TCGplayer lists it in both versions: confirmed, not asked again.
    assert scorcher.attributes["finishes_confirmed"] == "tcgcsv"
    assert set(scorcher.finishes) == {"normal", "foil"}
    fields = set(await session.scalars(select(CatalogDiscrepancy.field)))
    assert fields <= {"name", "rarity", "text"}

    async with http_client() as http:
        await prices.sync_prices(session, get_provider("riftbound"), http)
    quotes = (
        await session.execute(
            select(PriceSnapshot.currency, func.count())
            .where(PriceSnapshot.source == "tcgplayer")
            .group_by(PriceSnapshot.currency)
        )
    ).all()
    assert quotes and quotes[0][0] == "USD"
