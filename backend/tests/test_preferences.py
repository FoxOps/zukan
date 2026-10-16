"""User settings (language, catalog games), localized images, accent-free search,
Sorcery Cardmarket prices and game symbols."""

import io
from decimal import Decimal

import httpx
import pytest
import respx
from PIL import Image
from sqlalchemy import select

from app.core.config import get_settings
from app.games.base import registry
from app.games.pokemon.provider import ENERGY_SPRITE
from app.games.sorcery.provider import (
    CARDMARKET_EXPANSIONS,
    IMAGE_URL,
    match_cardmarket,
    parse_cards,
)
from app.models import CardName, CardSet, JobKind, PriceSnapshot, Printing
from app.services import images, jobs, symbols
from tests.conftest import SORCERY_CARDS, bearer, make_user, sync_sorcery


@pytest.fixture(autouse=True)
def image_dir(tmp_path):
    get_settings().image_dir = tmp_path / "images"


@pytest.fixture
async def alice(client, session, sorcery_api):
    from app.main import register_games

    await register_games()
    await sync_sorcery(session)
    await make_user(session)
    return await bearer(client, "alice")


async def printing(session, set_code: str, external_id: str) -> Printing:
    return await session.scalar(
        select(Printing)
        .join(CardSet)
        .where(CardSet.code == set_code, Printing.external_id == external_id)
    )


def png(width: int = 4, color: str = "red") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, width), color).save(out, "PNG")
    return out.getvalue()


async def test_settings_language_and_catalog_games(client, alice):
    me = (await client.get("/api/auth/me", headers=alice)).json()
    assert (me["language"], me["catalog_games"]) == ("en", None)

    response = await client.patch(
        "/api/auth/me", json={"language": "fr", "catalog_games": ["sorcery", "mtg"]}, headers=alice
    )
    assert response.status_code == 200, response.text
    # Stored in registry order.
    assert (response.json()["language"], response.json()["catalog_games"]) == (
        "fr",
        ["mtg", "sorcery"],
    )
    assert (
        await client.patch("/api/auth/me", json={"language": "de"}, headers=alice)
    ).status_code == 422
    unknown = await client.patch("/api/auth/me", json={"catalog_games": ["chess"]}, headers=alice)
    assert unknown.status_code == 422

    # Only the chosen games are listed when no game is asked for.
    await client.patch("/api/auth/me", json={"catalog_games": ["mtg"]}, headers=alice)
    assert (await client.get("/api/cards", headers=alice)).json()["total"] == 0
    asked = await client.get("/api/cards", params={"game": "sorcery"}, headers=alice)
    assert asked.json()["total"] == 7
    await client.patch("/api/auth/me", json={"catalog_games": None}, headers=alice)
    assert (await client.get("/api/cards", headers=alice)).json()["total"] == 7
    # Fields left out are kept.
    assert (await client.get("/api/auth/me", headers=alice)).json()["language"] == "fr"


async def test_search_ignores_case_and_accents(client, session, alice):
    abundance = await printing(session, "001", "abundance-b")
    session.add(CardName(card_id=abundance.card_id, lang="fr", name="Abondance Forêt"))
    await session.commit()
    for query in ("forêt", "FORET", "Foret", "abondance foret", "ABUNDANCE"):
        page = (await client.get("/api/cards", params={"q": query}, headers=alice)).json()
        assert [c["name"] for c in page["items"]] == ["Abundance"], query
    # Wildcards are literal.
    assert (await client.get("/api/cards", params={"q": "%"}, headers=alice)).json()["total"] == 0


async def test_owned_printings_come_first(client, session, alice):
    alpha = await printing(session, "001", "abundance-b")
    added = await client.post(
        "/api/collection/adjust",
        json={"printing_id": alpha.id, "finish": "standard", "language": "en", "delta": 1},
        headers=alice,
    )
    assert added.status_code == 200
    card = (await client.get(f"/api/cards/{alpha.card_id}", headers=alice)).json()
    # Beta is newer, Alpha is owned.
    assert [p["set"]["code"] for p in card["printings"]] == ["001", "002"]


async def test_image_in_user_language_with_fallbacks(client, session, alice):
    p = await printing(session, "001", "abundance-b")
    p.image_urls = {
        "en": "https://img.test/en.png",
        "fr": "https://img.test/fr.png",
        "ja": "https://img.test/ja.png",
    }
    await session.commit()
    url = f"/api/printings/{p.id}/image"
    with respx.mock as router:
        for lang, color in (("en", "red"), ("ja", "blue")):
            router.get(f"https://img.test/{lang}.png").respond(
                content=png(color=color), headers={"content-type": "image/png"}
            )
        router.get("https://img.test/fr.png").respond(404)

        def color(response) -> tuple:
            assert response.status_code == 200, response.text
            return Image.open(io.BytesIO(response.content)).getpixel((0, 0))

        # German: no scan, English. French: missing on the server, English too.
        assert color(await client.get(url, params={"lang": "de"}, headers=alice)) == (255, 0, 0)
        assert color(await client.get(url, params={"lang": "fr"}, headers=alice)) == (255, 0, 0)
        assert color(await client.get(url, params={"lang": "ja"}, headers=alice)) == (0, 0, 255)

    await session.refresh(p)
    assert p.image_paths["fr"] == ""  # not asked again
    # Without English, Japanese comes next.
    p.image_urls = {"ja": p.image_urls["ja"], "ko": "https://img.test/ko.png"}
    p.image_paths = {"ja": p.image_paths["ja"]}
    await session.commit()
    assert images.image_languages(p, "fr") == ["ja", "ko"]

    # Links carry the chosen language, so a language change is not hidden by the cache.
    await client.patch("/api/auth/me", json={"language": "fr"}, headers=alice)
    card = (await client.get(f"/api/cards/{p.card_id}", headers=alice)).json()
    shown = next(pr for pr in card["printings"] if pr["id"] == p.id)
    assert shown["image"].endswith("?lang=ja")
    p.image_urls = {**p.image_urls, "fr": "https://img.test/fr2.png"}
    p.image_paths = {**p.image_paths, "fr": ""}
    await session.commit()
    # A refused French download is not chosen.
    card = (await client.get(f"/api/cards/{p.card_id}", headers=alice)).json()
    shown = next(pr for pr in card["printings"] if pr["id"] == p.id)
    assert shown["image"].endswith("?lang=ja")
    p.image_paths = {**p.image_paths, "fr": "x.png"}
    await session.commit()
    card = (await client.get(f"/api/cards/{p.card_id}", headers=alice)).json()
    shown = next(pr for pr in card["printings"] if pr["id"] == p.id)
    assert shown["image"].endswith("?lang=fr")


async def test_sorcery_images_job_caches_every_printing(session, alice, monkeypatch):
    monkeypatch.setattr(images, "_REENCODE_ABOVE_BYTES", 100)
    big = png(width=900)
    with respx.mock as router:
        route = router.get(url__startswith=IMAGE_URL).respond(
            content=big, headers={"content-type": "image/png"}
        )
        await jobs.run_job("sorcery", JobKind.images)
        count = len((await session.scalars(select(Printing))).all())
        assert route.call_count == count
        # Standard finish scan preferred.
        assert any(c.request.url.path.endswith("-b-s.png") for c in route.calls)
        await jobs.run_job("sorcery", JobKind.images)
        assert route.call_count == count  # cached once

    p = await printing(session, "001", "abundance-b")
    await session.refresh(p)
    stored = get_settings().image_dir / p.image_paths["en"]
    assert stored.suffix == ".webp"
    assert Image.open(stored).width == images._REENCODE_WIDTH


CM_PRODUCTS = [
    # Alpha (known expansion); two "Avatar of Air" products: booster first by id.
    {"idProduct": 1, "name": "Abundance", "idExpansion": 6771},
    {"idProduct": 2, "name": "Avatar of Air", "idExpansion": 6771},
    {"idProduct": 3, "name": "Avatar of Air", "idExpansion": 6771},
    # Beta.
    {"idProduct": 4, "name": "Abundance", "idExpansion": 6775},
    # Unknown expansion, recognized as Arthurian Legends by its card names.
    {"idProduct": 5, "name": "13 Treasures of Britain", "idExpansion": 9001},
    {"idProduct": 6, "name": "Archimago", "idExpansion": 9001},
    # Not in the catalog.
    {"idProduct": 7, "name": "Unknown Card", "idExpansion": 9002},
]
CM_GUIDES = [
    {"idProduct": 1, "trend": 2.5, "low": 1, "avg": 2, "trend-foil": 30, "low-foil": 20},
    {"idProduct": 2, "trend": None, "avg7": None, "avg30": 4.4, "low": 3, "low-foil": 50},
    {"idProduct": 3, "trend": 1.1},
    {"idProduct": 4, "trend": 0, "avg7": 0.8, "low": 0.5, "trend-foil": None, "low-foil": 9},
    {"idProduct": 5, "trend": 7},
    {"idProduct": 6, "trend": 12},
]
CM_GUIDE = {g["idProduct"]: g for g in CM_GUIDES}


def test_cardmarket_matching(monkeypatch):
    monkeypatch.delitem(CARDMARKET_EXPANSIONS, 6778)  # Arthurian Legends
    quotes = {
        (q.set_external_id, q.printing_external_id, q.finish): q
        for q in match_cardmarket(parse_cards(SORCERY_CARDS), CM_PRODUCTS, CM_GUIDE)
    }
    alpha = quotes[("001", "abundance-b", "standard")]
    assert (alpha.trend, alpha.low, alpha.avg) == (Decimal("2.5"), Decimal("1"), Decimal("2"))
    assert quotes[("001", "abundance-b", "foil")].trend == Decimal("30")
    # Booster printing (foil only) gets the first product, the precon deck the second.
    assert quotes[("001", "avatar_of_air-b", "foil")].trend == Decimal("50")
    assert quotes[("001", "avatar_of_air-pd", "standard")].trend == Decimal("1.1")
    # No trend (0 = none): recent average.
    assert quotes[("002", "abundance-b", "standard")].trend == Decimal("0.8")
    assert quotes[("002", "abundance-b", "foil")].trend == Decimal("9")
    assert quotes[("004", "archimago-b", "standard")].trend == Decimal("12")
    assert ("999", "archimago-op", "rainbow") not in quotes


async def test_sorcery_price_job(session, alice, sorcery_router):
    files = {
        "/productCatalog/productList/products_singles_25.json": {"products": CM_PRODUCTS},
        "/productCatalog/priceGuide/price_guide_25.json": {"priceGuides": CM_GUIDES},
    }
    sorcery_router["cardmarket"].mock(
        side_effect=lambda request: httpx.Response(200, json=files[request.url.path])
    )
    await jobs.run_job("sorcery", JobKind.prices)
    p = await printing(session, "001", "abundance-b")
    snapshot = await session.scalar(
        select(PriceSnapshot).where(
            PriceSnapshot.printing_id == p.id, PriceSnapshot.finish == "standard"
        )
    )
    assert snapshot.trend == Decimal("2.50") and snapshot.source == "cardmarket"


async def test_cardmarket_links_and_price_range(client, session, sorcery_router):
    from app.main import register_games

    files = {
        "/productCatalog/productList/products_singles_25.json": {"products": CM_PRODUCTS},
        "/productCatalog/priceGuide/price_guide_25.json": {"priceGuides": CM_GUIDES},
    }
    sorcery_router["cardmarket"].mock(
        side_effect=lambda request: httpx.Response(200, json=files[request.url.path])
    )
    await register_games()
    await sync_sorcery(session)  # prices and product ids come with the catalog
    await make_user(session)
    headers = await bearer(client, "alice")

    games = {g["id"]: g for g in (await client.get("/api/games", headers=headers)).json()}
    assert games["sorcery"]["cardmarket"] == "Sorcery"
    assert games["mtg"]["cardmarket"] == "Magic"

    page = (await client.get("/api/cards", params={"q": "abundance"}, headers=headers)).json()
    # Beta standard 0.80 ... Alpha foil 30.
    summary = page["items"][0]
    assert (summary["price_min"], summary["price_max"]) == ("0.80", "30.00")
    card = (await client.get(f"/api/cards/{summary['id']}", headers=headers)).json()
    alpha = next(p for p in card["printings"] if p["set"]["code"] == "001")
    assert alpha["cardmarket_id"] == 1
    assert {(p["finish"], p["trend"], p["low"]) for p in alpha["prices"]} == {
        ("standard", "2.50", "1.00"),
        ("foil", "30.00", "20.00"),
    }
    unmatched = await client.get("/api/cards", params={"q": "aqueduct"}, headers=headers)
    assert unmatched.json()["items"][0]["price_min"] is None


async def test_symbols_downloaded_once(client, alice):
    games = {g["id"]: g for g in (await client.get("/api/games", headers=alice)).json()}
    assert games["mtg"]["colors"][0]["icon"] is None

    sheet = Image.new("RGBA", (100, 75))
    sheet.paste((0, 255, 0, 255), (25, 50, 50, 75))  # grass cell
    out = io.BytesIO()
    sheet.save(out, "PNG")
    with respx.mock as router:
        svg = router.get(url__startswith="https://svgs.scryfall.io/").respond(
            content=b"<svg/>", headers={"content-type": "image/svg+xml"}
        )
        sprite = router.get(ENERGY_SPRITE).respond(
            content=out.getvalue(), headers={"content-type": "image/png"}
        )
        elements = router.get(url__startswith="https://sorcerytcg.com/").respond(
            content=png(), headers={"content-type": "image/png"}
        )
        domains = router.get(url__startswith="https://cmsassets.rgpub.io/").respond(
            content=png(), headers={"content-type": "image/png"}
        )
        attributes = router.get(url__startswith="https://images.ygoprodeck.com/").respond(
            content=png(), headers={"content-type": "image/jpeg"}
        )
        stored = await symbols.ensure_symbols()
        # Symbols to download: Riftbound's colorless is drawn for Zukan (shipped), Yu-Gi-Oh!
        # spells and traps and Lorcana inks have none.
        downloaded = [
            c for p in registry().values() for c in p.colors if c.icon_url and not c.icon_file
        ]
        assert stored == len(downloaded)
        assert attributes.call_count == 7
        assert (sprite.call_count, svg.call_count, elements.call_count) == (1, 6, 4)
        assert domains.call_count == 6
        assert await symbols.ensure_symbols() == 0

    games = {g["id"]: g for g in (await client.get("/api/games", headers=alice)).json()}
    grass = next(c for c in games["pokemon"]["colors"] if c["code"] == "grass")
    icon = await client.get(grass["icon"], headers=alice)
    assert icon.status_code == 200
    image = Image.open(io.BytesIO(icon.content))
    assert image.size == (25, 25) and image.getpixel((5, 5)) == (0, 255, 0, 255)
    fire = next(c for c in games["sorcery"]["colors"] if c["code"] == "fire")
    assert (await client.get(fire["icon"], headers=alice)).headers["content-type"] == "image/png"
    assert (
        await client.get("/api/games/mtg/colors/..%2F..%2Fx/icon", headers=alice)
    ).status_code == 404
    colorless = next(c for c in games["riftbound"]["colors"] if c["code"] == "colorless")
    shipped = await client.get(colorless["icon"], headers=alice)
    assert shipped.status_code == 200 and shipped.content.startswith(b"<svg")


def test_api_tokens_follow_the_naming_rule(monkeypatch):
    from app.core.config import api_token

    monkeypatch.setenv("TCG_APITOKEN_GAMES_PKM_POKEMONTCG", "secret")
    monkeypatch.setenv("TCG_APITOKEN_PRICES_CARDNEXUS", "")
    assert api_token("games", "pokemontcg", "pkm") == "secret"
    assert api_token("prices", "cardnexus") is None
    assert api_token("prices", "nothing") is None
