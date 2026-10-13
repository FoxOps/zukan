"""OCR identification, with text as ML Kit returns it from real card photos."""

import httpx
import pytest
import respx

from app.core.http import http_client
from app.games.base import OcrLine, get_provider
from app.games.cardmarket import DOWNLOAD_URL as CARDMARKET_URL
from app.games.mtg.provider import API_URL as SCRYFALL
from app.games.pokemon.provider import API_URL as TCGDEX
from app.games.sorcery.provider import API_URL as SORCERY
from app.main import register_games
from app.services.catalog import sync_catalog
from tests.conftest import SORCERY_CARDS, bearer, make_user
from tests.test_mtg import ALL_URL, LINES, SETS, gz
from tests.test_pokemon import API as TCGDEX_API


def ocr(*texts: str) -> list[OcrLine]:
    return [OcrLine(t) for t in texts]


ELVES_FR = ocr(
    "Elfes de Llanowar G",
    "Créature : elfe et druide",
    "{T} : Ajoutez {G}.",
    "1/1",
    "168/269 C",
    "DOM • FR Chris Rahn",
    "™ & © 2018 Wizards of the Coast",
)
DELVER_OLD = ocr(
    "Delver of Secrets",
    "Creature — Human Wizard",
    "At the beginning of your upkeep, look at the top card of your library.",
    "1/1",
    "Illus. Nils Hamm",
    "51/264",
    "™ & © 2011 Wizards of the Coast LLC",
)
AJANI_JA = ocr("寛大なる者、アジャニ", "伝説のプレインズウォーカー", "184*/264 M", "WAR • JP")
FURRET_FR = ocr(
    "BASE",
    "Fouinar PV 110",
    "Évolue de Fouinette",
    "Bien-être Piochez 3 cartes.",
    "Illus. tetsuya koizumi",
    "136/189",
)
TROPIUS_JA = ocr("たね トロピウス HP110", "リーフドレイン 20", "SV1a 001/073 C")
ABUNDANCE = ocr(
    "Abundance",
    "An Elite Aura of milk and honey",
    "Each affected site provides one additional mana.",
    "Vincent Pompetti",
    "© 2023 Erik's Curiosa Limited",
)


def test_mtg_parser():
    mtg = get_provider("mtg")
    hints = mtg.parse_ocr(ELVES_FR)
    assert (hints.name, hints.set_code, hints.collector_number, hints.lang) == (
        "Elfes de Llanowar",
        "DOM",
        "168",
        "fr",
    )
    old = mtg.parse_ocr(DELVER_OLD)
    assert (old.name, old.set_code, old.collector_number) == ("Delver of Secrets", None, "51")
    ajani = mtg.parse_ocr(AJANI_JA)
    assert (ajani.set_code, ajani.collector_number, ajani.lang) == ("WAR", "184★", "ja")
    # New layout without set size, zero padded; power/toughness on the right is ignored.
    boxed = mtg.parse_ocr(
        [
            OcrLine("Forest", 0.06, 0.04),
            OcrLine("Basic Land — Forest", 0.06, 0.56),
            OcrLine("2/2", 0.82, 0.92),
            OcrLine("0280 L", 0.04, 0.93),
            OcrLine("BLB • EN Artist", 0.04, 0.95),
        ]
    )
    assert (boxed.name, boxed.collector_number, boxed.set_code) == ("Forest", "280", "BLB")


def test_pokemon_parser():
    pokemon = get_provider("pokemon")
    furret = pokemon.parse_ocr(FURRET_FR)
    assert (furret.name, furret.collector_number, furret.lang) == ("Fouinar", "136", "fr")
    tropius = pokemon.parse_ocr(TROPIUS_JA)
    assert (tropius.name, tropius.set_code, tropius.collector_number, tropius.lang) == (
        "トロピウス",
        "SV1a",
        "001",
        "ja",
    )
    sv = pokemon.parse_ocr(ocr("Basic Pikachu 70 HP", "Gnaw 20", "G PAL EN 063/193"))
    assert (sv.name, sv.set_code, sv.lang, sv.collector_number) == ("Pikachu", "PAL", "en", "063")


def test_sorcery_parser():
    hints = get_provider("sorcery").parse_ocr(ABUNDANCE)
    assert hints.name == "Abundance" and hints.collector_number is None


@pytest.fixture
async def catalogs(session, monkeypatch):
    """MTG, Pokémon and Sorcery fixture catalogs, synced one source at a time."""
    monkeypatch.setenv("TCG_POKEMON_LANGUAGES", '["en", "fr", "ja"]')
    await register_games()

    def tcgdex(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v2")
        return (
            httpx.Response(200, json=TCGDEX_API[path])
            if path in TCGDEX_API
            else httpx.Response(404)
        )

    for game, routes in (
        (
            "sorcery",
            lambda r: (
                r.get(SORCERY).respond(json=SORCERY_CARDS),
                r.get(url__startswith=CARDMARKET_URL).respond(404),
            ),
        ),
        ("pokemon", lambda r: r.get(url__startswith=TCGDEX).mock(side_effect=tcgdex)),
        (
            "mtg",
            lambda r: (
                r.get(f"{SCRYFALL}/sets").respond(json=SETS),
                r.get(f"{SCRYFALL}/bulk-data/all_cards").respond(
                    json={"jsonl_download_uri": ALL_URL}
                ),
                r.get(ALL_URL).respond(content=gz(LINES)),
            ),
        ),
    ):
        with respx.mock(assert_all_called=False) as router:
            routes(router)
            async with http_client() as http:
                await sync_catalog(session, get_provider(game), http)


@pytest.fixture
async def alice(client, session, catalogs):
    await make_user(session)
    return await bearer(client, "alice")


async def scan(client, headers, lines, game=None):
    body = {"lines": [{"text": line.text} for line in lines], "game": game}
    response = await client.post("/api/scan/identify", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.smoke
async def test_identify_exact_printing(client, alice):
    result = await scan(client, alice, ELVES_FR, game="mtg")
    best = result["candidates"][0]
    assert best["match"] == "set_number"
    assert best["card"]["name"] == "Llanowar Elves"
    assert (best["printings"][0]["set"]["code"], best["printings"][0]["collector_number"]) == (
        "DOM",
        "168",
    )
    assert result["detected"]["lang"] == "fr"

    ajani = (await scan(client, alice, AJANI_JA))["candidates"][0]
    assert ajani["match"] == "set_number"
    assert ajani["printings"][0]["collector_number"] == "184★"


async def test_identify_number_and_name(client, alice):
    result = await scan(client, alice, DELVER_OLD, game="mtg")
    best = result["candidates"][0]
    assert best["match"] == "number_name"
    assert best["printings"][0]["set"]["code"] == "ISD"

    furret = await scan(client, alice, FURRET_FR, game="pokemon")
    best = furret["candidates"][0]
    assert best["card"]["name"] == "Furret"
    assert best["printings"][0]["set"]["code"] == "DAA"
    assert best["printings"][0]["names"]["fr"] == "Fouinar"

    tropius = (await scan(client, alice, TROPIUS_JA))["candidates"][0]
    assert tropius["match"] == "set_number"
    assert tropius["card"]["name"] == "Tropius"  # interface language (English)


async def test_identify_ignores_accents_and_case(client, alice):
    # OCR often misses accents: "insectoide" still finds "Aberration insectoïde".
    for text in ("Aberration insectoïde", "ABERRATION INSECTOIDE"):
        body = {"game": "mtg", "lines": [{"text": text}]}
        response = await client.post("/api/scan/identify", json=body, headers=alice)
        assert response.json()["candidates"][0]["card"]["name"] == (
            "Delver of Secrets // Insectile Aberration"
        ), text


async def test_identify_by_name_detects_game(client, alice):
    result = await scan(client, alice, ABUNDANCE)
    assert result["game_id"] == "sorcery"
    best = result["candidates"][0]
    assert best["match"] == "name" and best["card"]["name"] == "Abundance"
    # Every printing offered, newest first (the phone lets the user pick).
    assert [p["set"]["code"] for p in best["printings"]] == ["002", "001"]

    # OCR typos still match.
    typo = await scan(client, alice, ocr("Llanowar Elvse"), game="mtg")
    assert typo["candidates"][0]["card"]["name"] == "Llanowar Elves"
    # Translated names, with the printing in that language first.
    japanese = await scan(client, alice, ocr("秘密を掘り下げる者", "クリーチャー"), game="mtg")
    assert japanese["candidates"][0]["card"]["name"].startswith("Delver of Secrets")


async def test_identify_reports_owned_copies(client, session, alice):
    result = await scan(client, alice, ELVES_FR, game="mtg")
    printing = result["candidates"][0]["printings"][0]
    await client.post(
        "/api/collection/adjust",
        json={"printing_id": printing["id"], "finish": "foil", "language": "fr", "delta": 2},
        headers=alice,
    )
    again = await scan(client, alice, ELVES_FR, game="mtg")
    owned = again["candidates"][0]["printings"][0]["owned"]
    assert [(o["finish"], o["language"], o["quantity"]) for o in owned] == [("foil", "fr", 2)]


async def test_identify_edge_cases(client, alice):
    assert (await scan(client, alice, ocr("zzzz qqqq xxxx")))["candidates"] == []
    assert (await scan(client, alice, []))["candidates"] == []
    unknown = await client.post(
        "/api/scan/identify", json={"lines": [], "game": "chess"}, headers=alice
    )
    assert unknown.status_code == 404
    too_many = await client.post(
        "/api/scan/identify", json={"lines": [{"text": "x"}] * 201}, headers=alice
    )
    assert too_many.status_code == 422
