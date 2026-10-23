import json

import respx

from app.core.config import get_settings
from app.core.http import http_client
from app.games.base import CatalogIndex
from app.games.pokemon import official_jp
from app.games.pokemon.official_jp import Cache, Wanted


def listed(card_id: str, picture: str, name: str) -> dict:
    return {
        "cardID": card_id,
        "cardThumbFile": f"/assets/images/card_images/large/{picture}",
        "cardNameViewText": name,
    }


LIST = [
    # Newest first, about 40 a page.
    [
        listed("50613", "M6a/050613_P_TAMATAMA.jpg", "タマタマ"),
        listed("50700", "M6a/050700_P_PIKA.jpg", "ピカチュウ"),
    ],
    [
        listed("50701", "M6a/050701_P_PIKA.jpg", "ピカチュウ"),
        listed("40000", "SV9/040000_P_X.jpg", "アローラ　ナッシー"),
    ],
]
DETAIL = (
    '<div class="subtext Text-fjalla"><img src="/x/M6a.gif" alt="M6a" />'
    "\n&nbsp;{number}&nbsp;/&nbsp;103&nbsp;\n</div>"
)


def wanted(code, number, name, ext=None):
    return Wanted(code.lower(), code, ext or number, number, f"ja:{name}", name, name)


def routes(router):
    def page(request):
        n = int(request.url.params["page"])
        return respx.MockResponse(
            200, json={"result": 1, "maxPage": len(LIST), "cardList": LIST[n - 1]}
        )

    pages = router.get(official_jp.LIST_URL).mock(side_effect=page)
    details = {
        "50700": router.get(official_jp.CARD_URL.format(id="50700")).respond(
            text=DETAIL.format(number="025")
        ),
        "50701": router.get(official_jp.CARD_URL.format(id="50701")).respond(
            text=DETAIL.format(number="130")
        ),
    }
    return pages, details


async def run() -> list:
    async with http_client() as http:
        return [
            b async for b in official_jp.source.fetch(http, CatalogIndex(sets={}, printings={}))
        ]


async def test_pictures_of_japanese_printings(monkeypatch, tmp_path):
    monkeypatch.setenv("TCG_POKEMON_OFFICIAL_JP", "true")
    monkeypatch.setattr(get_settings(), "image_dir", tmp_path)
    ours = [
        wanted("M6a", "001", "タマタマ"),
        # Two cards of one name in the set: told apart by their numbers.
        wanted("M6a", "25", "ピカチュウ"),
        wanted("M6a", "130", "ピカチュウ"),
        # Full-width space in their name.
        wanted("SV9", "050", "アローラ ナッシー"),
        # Not on their site.
        wanted("M6a", "099", "ミュウ"),
    ]

    async def wanted_printings():
        return ours

    monkeypatch.setattr(official_jp, "wanted_printings", wanted_printings)
    with respx.mock(assert_all_called=False) as router:
        pages, details = routes(router)
        batches = await run()
    pictures = {
        (b.checked_sets[0], c.printings[0].external_id): c.printings[0].images["ja"]
        for b in batches
        for c in b.cards
    }
    base = "https://www.pokemon-card.com/assets/images/card_images/large"
    assert pictures == {
        ("m6a", "001"): f"{base}/M6a/050613_P_TAMATAMA.jpg",
        ("m6a", "25"): f"{base}/M6a/050700_P_PIKA.jpg",
        ("m6a", "130"): f"{base}/M6a/050701_P_PIKA.jpg",
        ("sv9", "050"): f"{base}/SV9/040000_P_X.jpg",
    }
    assert pages.call_count == 2
    cache = json.loads((tmp_path / "cache" / "pokemon-card-jp.json").read_text())
    assert cache["complete"] and cache["numbers"] == {"50700": "025", "50701": "130"}

    # Next run, same day: nothing asked again.
    with respx.mock(assert_all_called=False) as router:
        pages, details = routes(router)
        assert len(await run()) == 2
    assert pages.call_count == 0 and all(d.call_count == 0 for d in details.values())

    # Next day: the first page only, which has nothing new.
    cache = Cache()
    cache.read_at = "2000-01-01T00:00:00+00:00"
    cache.save()
    with respx.mock(assert_all_called=False) as router:
        pages, _ = routes(router)
        await run()
    assert pages.call_count == 1


async def test_off_by_setting(monkeypatch):
    async def fail():
        raise AssertionError("not asked")

    monkeypatch.setattr(official_jp, "wanted_printings", fail)
    assert await run() == []
