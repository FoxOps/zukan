import gzip
import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
import respx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.http import http_client
from app.games.base import StoredPrinting, get_provider
from app.models import CardSet, PriceSnapshot, Printing
from app.prices.base import MarketTarget
from app.services import prices
from app.sources import cardnexus
from tests.conftest import sync_sorcery

TODAY = date.today()
FEEDS = f"{cardnexus.BASE_URL}/feeds/sorcery"
FILES = "https://feeds.example/sorcery"


def gz(records: list[dict]) -> bytes:
    return gzip.compress("\n".join(json.dumps(r) for r in records).encode())


@pytest.fixture
def key(monkeypatch, tmp_path):
    monkeypatch.setenv("TCG_APITOKEN_PRICES_CARDNEXUS", "cnk_test")
    monkeypatch.setattr(get_settings(), "image_dir", tmp_path)


def mock_feeds(router, files: dict[str, bytes]) -> list:
    router.get(FEEDS).respond(
        json={
            kind: {
                "url": f"{FILES}/{kind}.ndjson.gz?sig=1",
                "checksum": hashlib.sha256(gzip.decompress(body)).hexdigest(),
            }
            for kind, body in files.items()
        }
    )
    return [
        router.get(f"{FILES}/{kind}.ndjson.gz").respond(content=body)
        for kind, body in files.items()
    ]


def test_quotes_from_their_price_blocks():
    target = MarketTarget(
        "set", "001", ("normal", "holo", "reverse"), quoted=frozenset({"tcgplayer"})
    )
    fresh = (TODAY - timedelta(days=2)).isoformat()
    old = (TODAY - timedelta(days=200)).isoformat()

    def tiers(currency, low, mid, market, day=fresh):
        return {"currency": currency, "low": low, "mid": mid, "marketValue": market, "date": day}

    blocks = {
        "Standard": {
            "cardmarket": tiers("EUR", 0.1, 0.3, 0.25),
            # Already priced today by its own source.
            "tcgplayer": tiers("USD", 0.2, 0.4, 0.3),
            "cardnexus": {"low": {"amount": 0.15, "currency": "EUR"}, "listingCount": 3},
        },
        # No recent sale: left out.
        "Foil": {"cardmarket": tiers("EUR", 5, 9, 8, old)},
        "Reverse Holo": {"cardnexus": {"low": {"amount": 1.2, "currency": "EUR"}}},
        # Not a finish of the printing.
        "Rainbow": {"cardnexus": {"low": {"amount": 99, "currency": "EUR"}}},
    }  # fmt: skip
    quotes = cardnexus.quotes_for("pokemon", target, blocks, TODAY)
    assert sorted((q.source, q.finish, q.trend, q.low, q.avg) for q in quotes) == [
        ("cardmarket", "normal", Decimal("0.25"), Decimal("0.1"), Decimal("0.3")),
        ("cardnexus", "normal", Decimal("0.15"), Decimal("0.15"), None),
        ("cardnexus", "reverse", Decimal("1.2"), Decimal("1.2"), None),
    ]
    assert cardnexus.finish_code("mtg", "Standard") == "nonfoil"
    assert cardnexus.finish_code("sorcery", "Rainbow") == "rainbow"


def test_expansions_and_links():
    found = cardnexus.parse_expansion(
        {"id": 1170, "name": "ME01: Mega Evolution", "code": "me01-mega-evolution",
         "releaseDate": "2025-09-26T00:00:00.000Z", "attributes": {"setId": None}}
    )  # fmt: skip
    assert (found.key, found.name, found.codes[0], found.release_date) == (
        1170,
        "Mega Evolution",
        "ME01",
        date(2025, 9, 26),
    )
    raw = {"id": 154426, "nameSlug": "mega-diancie-ex", "expansionSlug": "me02-phantasmal-flames",
           "externalIds": {"cardmarket": [{"finish": "Foil", "id": 857000}]}}  # fmt: skip
    ids = cardnexus.market_ids(raw, "pokemon")
    assert ids == {
        "cardnexus": "pokemon/me02-phantasmal-flames/card/mega-diancie-ex-154426",
        "cardmarket": "857000",
    }
    assert cardnexus.product_id(ids["cardnexus"]) == 154426
    assert cardnexus.link(ids["cardnexus"], "ja") == (
        "https://cardnexus.com/en/explore/pokemon/me02-phantasmal-flames/card/mega-diancie-ex-154426"
    )


def stored(number: str, name: str, **extra) -> StoredPrinting:
    return StoredPrinting(
        set_external_id="me02",
        external_id=number,
        collector_number=number,
        rarity=extra.get("rarity"),
        artist=None,
        card_external_id=f"en:{name.casefold()}",
        card_name=name,
        image_languages=extra.get("images", ("en",)),
        market_ids=extra.get("market_ids", {}),
        languages=("en",),
        finishes=("holo",),
    )


def product(pid: int, number: str, name: str, **extra) -> cardnexus.Product:
    raw = {
        "id": pid,
        "name": name,
        "nameSlug": name.casefold().replace(" ", "-"),
        "expansionSlug": "me02-phantasmal-flames",
        "printNumber": number,
        "rarity": "DOUBLE_RARE",
        "finishes": ["Foil"],
        "languages": ["en", "fr", "pt-BR"],
        "imageUrl": f"https://img.example/{pid}.png",
        "externalIds": {"tcgplayer": [{"finish": "Foil", "id": pid + 1}]},
        "attributes": {"artist": "Someone"},
    } | extra
    return cardnexus.Product(raw, "pokemon")


def test_set_gaps_filled_and_missing_printings_added():
    ours = [
        stored("041", "Mega Diancie ex", images=()),
        stored("056", "Mega Gengar ex", rarity="Double rare", market_ids={"tcgplayer": "7"}),
    ]
    theirs = [
        product(1, "041", "Mega Diancie ex"),
        product(2, "056", "Mega Gengar ex"),
        # Missing from the set, of a card we have: added, numbered like the set.
        product(3, "94", "Mega Gengar ex"),
        # A card we do not have at all: not invented.
        product(4, "095", "Unknown ex"),
    ]
    names = {p.card_name.casefold(): (p.card_external_id, p.card_name) for p in ours}
    batch = cardnexus.check_products("pokemon", ours, theirs, names)
    assert batch.matched == 2
    by_number = {c.printings[0].external_id: c for c in batch.cards}
    diancie = by_number["041"].printings[0]
    assert diancie.images == {"en": "https://img.example/1.png"}
    assert diancie.rarity == "Double Rare" and diancie.artist == "Someone"
    assert diancie.attributes["market_ids"] == {
        "tcgplayer": "2",
        "cardnexus": "pokemon/me02-phantasmal-flames/card/mega-diancie-ex-1",
    }
    # Only the market id it lacked.
    gengar = by_number["056"].printings[0]
    assert gengar.attributes["market_ids"] == {
        "cardnexus": "pokemon/me02-phantasmal-flames/card/mega-gengar-ex-2"
    }
    added = by_number["094"]
    assert (added.external_id, added.partial) == ("en:mega gengar ex", True)
    printing = added.printings[0]
    assert (printing.collector_number, printing.partial, printing.finishes) == (
        "094",
        False,
        ["holo"],
    )
    assert printing.languages == ["en", "fr", "pt"]
    assert printing.attributes["added_by"] == "cardnexus"
    assert "095" not in by_number

    # Printings keyed otherwise than on their number (Magic): nothing added.
    other = [stored("041", "Mega Diancie ex")]
    other[0] = StoredPrinting(**{**other[0].__dict__, "external_id": "a1b2"})
    batch = cardnexus.check_products("pokemon", other, theirs, names)
    assert all(not p.printings[0].collector_number for p in batch.cards)


@pytest.mark.gap_sources
async def test_prices_from_the_daily_files(session, sorcery_api, key, monkeypatch):
    from app.main import register_games

    await register_games()
    await sync_sorcery(session)
    printing = await session.scalar(
        select(Printing)
        .join(CardSet)
        .where(CardSet.game_id == "sorcery")
        .order_by(Printing.id)
        .limit(1)
    )
    printing.attributes = {**printing.attributes, "market_ids": {"cardmarket": "555"}}
    await session.commit()
    finish = printing.finishes[0]
    their_finish = {"standard": "Standard", "foil": "Foil", "rainbow": "Rainbow"}[finish]
    files = {
        "catalog": gz([
            {"id": 9, "productType": "card", "name": "X", "nameSlug": "x", "expansionSlug": "beta",
             "externalIds": {"cardmarket": [{"finish": their_finish, "id": 555}]}},
            {"id": 10, "productType": "sealed", "name": "Box"},
        ]),
        "prices": gz([
            {"productId": 9, "pricesByFinish": {their_finish: {
                "cardnexus": {"low": {"amount": 4.5, "currency": "EUR"}},
                "tcgplayer": {"currency": "USD", "low": 4, "mid": 5, "marketValue": 6,
                              "date": TODAY.isoformat()},
            }}},
        ]),
    }  # fmt: skip

    async def no_cardmarket(self, http, owned):
        return
        yield

    monkeypatch.setattr(type(get_provider("sorcery")), "fetch_prices", no_cardmarket)
    with respx.mock(assert_all_called=False) as router:
        mock_feeds(router, files)
        router.get(url__startswith="https://tcgcsv.com").respond(404)
        async with http_client() as http:
            report = await prices.sync_prices(session, get_provider("sorcery"), http)
    assert report.stored >= 2
    rows = (
        await session.execute(
            select(PriceSnapshot.source, PriceSnapshot.trend, PriceSnapshot.currency).where(
                PriceSnapshot.printing_id == printing.id
            )
        )
    ).all()
    assert sorted(rows) == [
        ("cardnexus", Decimal("4.50"), "EUR"),
        ("tcgplayer", Decimal("6.00"), "USD"),
    ]
    # Files kept: an unchanged checksum downloads nothing the next day.
    with respx.mock(assert_all_called=False) as router:
        routes = mock_feeds(router, files)
        async with http_client() as http:
            feeds = cardnexus.Feeds(http, cardnexus.budget())
            assert await feeds.path("sorcery", "catalog") is not None
            assert await feeds.path("sorcery", "expansions") is None
        assert [r.call_count for r in routes] == [0, 0]


async def test_skipped_without_key(monkeypatch):
    monkeypatch.delenv("TCG_APITOKEN_PRICES_CARDNEXUS", raising=False)
    assert cardnexus.source.for_game("pokemon") is None
    from app.prices.cardnexus import source as prices_source

    assert prices_source.games == set()
