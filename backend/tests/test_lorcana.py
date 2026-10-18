import importlib
import json
from pathlib import Path

import pytest
import respx
from sqlalchemy import select

from app.core.http import http_client
from app.games.base import OcrLine, get_provider, rarity_of
from app.games.cardmarket import DOWNLOAD_URL as CARDMARKET_URL
from app.main import register_games
from app.models import PriceSnapshot, Printing
from app.services.catalog import sync_catalog

lorcana = importlib.import_module("app.games.lorcana.provider")
DATA = json.loads((Path(__file__).parent / "fixtures" / "lorcana.json").read_text())
FILES = {lang: DATA[lang] for lang in lorcana.LANGUAGES}


def by_name(batch):
    return {c.name: c for c in batch.cards}


def test_catalog():
    batch = lorcana.build_catalog(FILES)
    cards = by_name(batch)
    ariel = cards["Ariel - On Human Legs"]
    assert ariel.colors == ["amber"] and ariel.names["fr"] == "Ariel - Sur des jambes humaines"
    (printing,) = ariel.printings
    assert (printing.set_external_id, printing.collector_number, printing.rarity) == (
        "1",
        "1",
        "Uncommon",
    )
    # No Italian printing of the first sets.
    assert printing.finishes == ["normal", "foil"] and printing.languages == ["en", "fr", "de"]
    assert printing.attributes["market_ids"]["cardmarket"] == 727081
    assert "fr" in printing.images
    # Enchanted and plain Hades: one card, the enchanted one foil only.
    hades = cards["Hades - King of Olympus"]
    enchanted = next(p for p in hades.printings if p.rarity == "Enchanted")
    assert enchanted.finishes == ["foil"] and enchanted.attributes["foil_type"] == "Lava"
    assert rarity_of("lorcana", enchanted.rarity).code == "enchanted"
    # Promos get a set per promo group, variants a letter.
    mickey = cards["Mickey Mouse - Brave Little Tailor"]
    assert any(p.set_external_id == "P1" and p.collector_number == "1/P1" for p in mickey.printings)
    assert (
        by_name(batch)["Dalmatian Puppy - Tail Wagger"].printings[0].collector_number[-1] in "abcde"
    )
    assert len(cards["Rhino - Motivational Speaker"].colors) == 2
    assert {s.external_id for s in batch.sets} >= {"1", "P1"}


def test_quest_and_promo_rarities():
    files = json.loads(json.dumps(FILES))
    files["en"]["sets"]["Q2"] = {"type": "quest", "name": "Illumineer's Quest: Palace Heist"}
    quest = next(c for c in files["en"]["cards"] if c.get("promoGrouping"))
    files["en"]["cards"].append(
        {**quest, "id": 99999, "setCode": "Q2", "promoGrouping": None, "fullName": "Abu - Q"}
    )
    batch = lorcana.build_catalog(files)
    cards = by_name(batch)
    # LorcanaJSON's "Special": a promo (promo group) or an Illumineer's Quest card.
    promo = next(p for p in cards[quest["fullName"]].printings if p.set_external_id == "P1")
    assert promo.rarity == "Promo" and rarity_of("lorcana", promo.rarity).code == "promo"
    (abu,) = cards["Abu - Q"].printings
    assert abu.rarity == "Quest" and rarity_of("lorcana", abu.rarity).code == "quest"
    assert not any(p.rarity == "Special" for c in batch.cards for p in c.printings)


def test_rules_text_spells_out_symbols():
    assert lorcana.rules_text("Shift 3 ⬡ (pay 3 ⬡)") == "Shift 3 Ink (pay 3 Ink)"
    assert lorcana.rules_text("can ⟳ to sing, +1 ◊") == "can [Exert] to sing, +1 Lore"


def test_cardmarket_prices_by_id():
    batch = lorcana.build_catalog(FILES)
    guides = {g["idProduct"]: g for g in DATA["cardmarket_guides"]}
    quotes = lorcana.cardmarket_quotes(batch, guides)
    hades = by_name(batch)["Hades - King of Olympus"]
    enchanted = next(p for p in hades.printings if p.rarity == "Enchanted")
    assert any(
        q.printing_external_id == enchanted.external_id and q.finish == "foil" for q in quotes
    )
    assert {q.source for q in quotes} == {"cardmarket"}


@pytest.fixture
async def router():
    await register_games()
    with respx.mock(assert_all_called=False) as router:
        for lang, data in FILES.items():
            router.get(lorcana.DATA_URL.format(lang=lang)).respond(json=data)
        router.get(f"{CARDMARKET_URL}/priceGuide/price_guide_19.json").respond(
            json={"priceGuides": DATA["cardmarket_guides"]}
        )
        yield router


async def test_sync(session, router):
    async with http_client() as http:
        report = await sync_catalog(session, get_provider("lorcana"), http)
    assert report.cards == 5 and report.printings == 6
    priced = await session.scalar(
        select(PriceSnapshot.trend)
        .join(Printing, PriceSnapshot.printing_id == Printing.id)
        .where(Printing.external_id == "1", PriceSnapshot.finish == "normal")
    )
    assert priced is not None


def test_parse_ocr():
    provider = get_provider("lorcana")
    hints = provider.parse_ocr(
        [
            OcrLine("Ariel", 0.1, 0.55),
            OcrLine("On Human Legs", 0.1, 0.6),
            OcrLine("Matthew Robert Davies", 0.05, 0.94),
            OcrLine("1/204 • EN • 1", 0.05, 0.97),
            OcrLine("© Disney", 0.6, 0.97),
        ]
    )
    assert (hints.set_code, hints.collector_number, hints.lang, hints.name) == (
        "1",
        "1",
        "en",
        "Ariel",
    )
    assert hints.recognized
    promo = provider.parse_ocr([OcrLine("TFC • EN • 1/P1", 0.05, 0.97)])
    assert (promo.set_code, promo.collector_number) == ("P1", "1/P1")
