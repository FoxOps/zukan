from decimal import Decimal

import respx

from app.core.http import http_client
from app.games.cardmarket import DOWNLOAD_URL
from app.prices.base import MarketTarget
from app.prices.cardmarket import source


def test_guide_games():
    assert {"pokemon", "pokemon-asia"} <= source.games
    assert "pokemon-china" not in source.games


async def test_guide_prices_printings_left_unpriced():
    targets = [
        MarketTarget("sv2a", "001", ("normal", "reverse"), {"cardmarket": "100"}),
        # Already priced today by TCGdex.
        MarketTarget("sv2a", "002", ("normal",), {"cardmarket": "101"}, frozenset({"cardmarket"})),
        MarketTarget("sv2a", "003", ("normal",), {}),
        MarketTarget("sv2a", "004", ("holo",), {"cardmarket": "102"}),
    ]
    guides = {
        "priceGuides": [
            {"idProduct": 100, "trend": 1.5, "low": 1, "avg": 1.4, "trend-holo": 3, "low-holo": 2},
            {"idProduct": 101, "trend": 9},
            # No trend yet: the recent average stands in.
            {"idProduct": 102, "trend": 0, "avg7": 4.2, "low": 4},
        ]
    }
    with respx.mock() as router:
        route = router.get(f"{DOWNLOAD_URL}/priceGuide/price_guide_6.json").respond(json=guides)
        async with http_client() as http:
            quotes = [
                q async for batch in source.fetch(http, "pokemon-asia", targets) for q in batch
            ]
    assert route.call_count == 1
    got = {(q.printing_external_id, q.finish): (q.trend, q.low, q.source) for q in quotes}
    assert got == {
        ("001", "normal"): (Decimal("1.5"), Decimal("1"), "cardmarket"),
        ("001", "reverse"): (Decimal("3"), Decimal("2"), "cardmarket"),
        ("004", "holo"): (Decimal("4.2"), Decimal("4"), "cardmarket"),
    }


async def test_nothing_to_price_downloads_nothing():
    targets = [MarketTarget("sv2a", "003", ("normal",), {})]
    with respx.mock() as router:
        async with http_client() as http:
            assert [b async for b in source.fetch(http, "pokemon", targets)] == []
        assert not router.calls
