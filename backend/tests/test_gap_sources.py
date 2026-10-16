from datetime import date

import pytest
import respx

from app.core.budget import BudgetSpent, RequestBudget
from app.core.config import get_settings
from app.core.http import http_client
from app.games.base import CatalogIndex, SetData, StoredPrinting
from app.main import register_games
from app.sources import apitcg, tcgapi_eu
from app.sources.base import (
    ExternalPrinting,
    ExternalSet,
    fill,
    match_sets,
    pair,
    plain_name,
    printing_gaps,
)

pytestmark = pytest.mark.gap_sources


def stored(number: str, name: str, **kwargs) -> StoredPrinting:
    values = dict(
        set_external_id="sv01",
        external_id=number,
        collector_number=number,
        rarity="Rare",
        artist="Ken",
        card_external_id=f"card-{name}",
        card_name=name,
        image_languages=("en",),
        market_ids={"tcgplayer": "1"},
        languages=("en",),
        finishes=("normal",),
    )
    return StoredPrinting(**{**values, **kwargs})


def index(*printings: StoredPrinting) -> CatalogIndex:
    sets = {
        "sv01": SetData("sv01", "SVI", "Scarlet & Violet", release_date=date(2023, 3, 31)),
        "asia:sv1": SetData("asia:sv1", "SV1", "Japanese set", lang="ja"),
    }
    return CatalogIndex(sets, {(p.set_external_id, p.external_id): p for p in printings})


def test_rules_text_differences_ignore_reminders_and_case():
    ours = stored("1", "Sentry", card_text="[Deflect]\nWhen you play me, draw 1.")
    same = ExternalPrinting(
        "1", "Sentry", text="[DEFLECT] (Opponents pay 1 Rune.) When you play me, draw 1."
    )
    other = ExternalPrinting("1", "Sentry", text="[DEFLECT] When you play me, draw 2.")
    assert fill("riftbound", "tcgcsv", ours, same, check_text=True) == (None, [])
    _, found = fill("riftbound", "tcgcsv", ours, other, check_text=True)
    assert [(d.field, d.primary) for d in found] == [("text", ours.card_text)]


def test_matching_helpers():
    ours = index().sets
    theirs = [
        ExternalSet("sv1", "Scarlet & Violet", ["sv1", "SVI"]),
        ExternalSet("x", "Something else", ["ZZZ"]),
    ]
    # "sv1" = "sv01"; Japanese sets are not English sets.
    assert match_sets(ours, theirs, "pokemon") == {"sv1": "sv01"}
    assert plain_name("Pikachu - 025/165") == "Pikachu"
    assert plain_name("Ahri - Alluring (Alternate Art)") == "Ahri - Alluring"
    a, b = stored("25", "Pikachu"), stored("25a", "Pikachu", market_ids={})
    pairs = pair([a, b], [ExternalPrinting("025a/165", "Pikachu"), ExternalPrinting("1", "X")])
    assert [(p.external_id, e.number) for p, e in pairs] == [("25a", "025a/165")]
    assert printing_gaps(a) == set()
    assert printing_gaps(stored("1", "X", artist=None, languages=("ja",))) == set()


async def test_budget_stops_at_its_limit():
    budget = RequestBudget("test-source", "month", 2)
    await budget.take()
    await budget.take()
    with pytest.raises(BudgetSpent):
        await budget.take()
    assert await budget.remaining() == 0
    # Another run in the same month shares the count.
    with pytest.raises(BudgetSpent):
        await RequestBudget("test-source", "month", 2).take()


async def test_without_key_the_sources_are_skipped(monkeypatch):
    await register_games()
    monkeypatch.delenv("TCG_APITOKEN_GAMES_APITCG", raising=False)
    monkeypatch.delenv("TCG_APITOKEN_GAMES_TCGAPIEU", raising=False)
    assert apitcg.source.for_game("pokemon") is None
    assert tcgapi_eu.source.for_game("pokemon") is None
    monkeypatch.setenv("TCG_APITOKEN_GAMES_APITCG", "test-key")
    assert apitcg.source.for_game("pokemon") is not None
    assert apitcg.source.for_game("sorcery") is None  # not on apitcg


async def test_apitcg_fills_gaps_within_its_quota(monkeypatch):
    await register_games()
    monkeypatch.setenv("TCG_APITOKEN_GAMES_APITCG", "test-key")
    monkeypatch.setattr(get_settings(), "apitcg_monthly_requests", 2)
    complete = stored("1", "Sprigatito")
    missing = stored("25", "Pikachu", artist=None, market_ids={}, image_languages=())
    with respx.mock as router:
        sets = router.get(f"{apitcg.BASE_URL}/pokemon/sets").respond(
            json={"data": [{"_id": "pokemon-sv1", "name": "Scarlet & Violet", "code": "SVI"}],
                  "total": 1}
        )  # fmt: skip
        products = router.get(f"{apitcg.BASE_URL}/products").respond(
            json={"total": 1, "data": [{
                "_id": 1, "name": "Pikachu - 025/198", "code": "025/198",
                "images": [{"large": "https://tcgplayer-cdn.tcgplayer.com/product/9_in_1000x1000.jpg"}],
                "markets": {"tcgplayer": {"id": "9", "printings": [{"subTypeName": "Normal"}]}},
                "attributes": {"Number": "025/198", "Rarity": "Rare", "Artist": "Kagemaru"},
            }]}
        )  # fmt: skip
        async with http_client() as http:
            bound = apitcg.source.for_game("pokemon")
            batches = [b async for b in bound.fetch(http, index(complete, missing))]
        assert sets.calls[0].request.headers["x-api-key"] == "test-key"
        assert products.calls[0].request.url.params["set"] == "pokemon-sv1"
    (batch,) = batches
    assert batch.matched == 1
    (card,) = batch.cards
    (printing,) = card.printings
    assert (printing.artist, printing.attributes["market_ids"]) == ("Kagemaru", {"tcgplayer": "9"})
    assert printing.images == {
        "en": "https://tcgplayer-cdn.tcgplayer.com/product/9_in_1000x1000.jpg"
    }

    # The 2 requests of the month are used: the next run asks nothing.
    with respx.mock:
        async with http_client() as http:
            assert [b async for b in bound.fetch(http, index(missing))] == []


async def test_tcgapi_eu_pages_only_sets_with_gaps(monkeypatch):
    await register_games()
    monkeypatch.setenv("TCG_APITOKEN_GAMES_TCGAPIEU", "test-key")
    missing = stored("25", "Pikachu", image_languages=())
    with respx.mock as router:
        router.get(f"{tcgapi_eu.BASE_URL}/pokemon/sets").respond(
            json={"data": {"sets": [{"id": "sv1", "name": "Scarlet & Violet", "ptcgo_code": "SVI",
                                     "release_date": "2023-03-31T00:00:00.000Z"}],
                           "pagination": {"hasNext": False}}}
        )  # fmt: skip
        cards = router.get(f"{tcgapi_eu.BASE_URL}/pokemon/cards").respond(
            json={"data": {"cards": [{"number": "25", "name": "Pikachu", "rarity": "Rare",
                                      "large_image_url": "https://tcg-images.example/25.webp"}],
                           "pagination": {"hasNext": False}}}
        )  # fmt: skip
        async with http_client() as http:
            bound = tcgapi_eu.source.for_game("pokemon")
            batches = [b async for b in bound.fetch(http, index(missing))]
            assert [b async for b in bound.fetch(http, index(stored("1", "X")))] == []
        assert cards.call_count == 1
        assert cards.calls[0].request.headers["X-API-Key"] == "test-key"
    assert batches[0].cards[0].printings[0].images == {"en": "https://tcg-images.example/25.webp"}
