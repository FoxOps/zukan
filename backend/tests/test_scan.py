"""OCR identification, with text as ML Kit returns it from real card photos."""

import httpx
import pytest
import respx

from app.core.http import http_client
from app.games.base import OcrLine, get_provider
from app.games.cardmarket import DOWNLOAD_URL as CARDMARKET_URL
from app.games.mtg.provider import API_URL as SCRYFALL
from app.games.pokemon import shared as pokemon_shared
from app.games.pokemon.provider import API_URL as TCGDEX
from app.games.sorcery.provider import API_URL as SORCERY
from app.main import register_games
from app.services.catalog import sync_catalog
from tests.conftest import SORCERY_CARDS, bearer, make_user
from tests.test_mtg import ALL_URL, LINES, SETS, gz
from tests.test_pokemon import API as TCGDEX_API
from tests.test_pokemon import _listings as tcgdex_listings


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
    # 8th Edition white border: number at the end of the copyright line, no set code.
    eighth = mtg.parse_ocr(
        [
            OcrLine("Serra Angel 3WW", 0.07, 0.04),
            OcrLine("Creature — Angel", 0.07, 0.56),
            OcrLine("Flying, vigilance", 0.08, 0.62),
            OcrLine("Illus. Douglas Shuler", 0.05, 0.91),
            OcrLine("4/4", 0.84, 0.90),
            OcrLine("™ & © 1993-2003 Wizards of the Coast, Inc. 47/350", 0.12, 0.95),
        ]
    )
    assert (eighth.name, eighth.collector_number, eighth.set_code) == ("Serra Angel", "47", None)
    assert eighth.recognized
    # The number read as its own block on the right, the year must not be taken.
    split = mtg.parse_ocr(
        [
            OcrLine("Serra Angel", 0.07, 0.04),
            OcrLine("Illus. Douglas Shuler", 0.05, 0.91),
            OcrLine("™ & © 2003 Wizards of the Coast, Inc.", 0.10, 0.95),
            OcrLine("47/350", 0.78, 0.95),
        ]
    )
    assert split.collector_number == "47"
    year_only = mtg.parse_ocr(ocr("Serra Angel", "Creature", "™ & © 2003 Wizards of the Coast"))
    assert year_only.collector_number is None


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
    # Japanese text has no spaces: stage and HP labels touch the name.
    packed = pokemon.parse_ocr(ocr("たねトロピウスHP110", "リーフドレイン 20", "SV1a 001/073 C"))
    assert packed.name == "トロピウス"
    # The set code box read as its own line.
    boxed = pokemon.parse_ocr(ocr("2進化 ドゴーム HP100", "G", "SV4K", "078/066 U"))
    assert (boxed.name, boxed.set_code, boxed.collector_number) == ("ドゴーム", "SV4K", "078")
    sv = pokemon.parse_ocr(ocr("Basic Pikachu 70 HP", "Gnaw 20", "G PAL EN 063/193"))
    assert (sv.name, sv.set_code, sv.lang, sv.collector_number) == ("Pikachu", "PAL", "en", "063")


def test_sorcery_parser():
    hints = get_provider("sorcery").parse_ocr(ABUNDANCE)
    assert hints.name == "Abundance" and hints.collector_number is None


@pytest.fixture
async def catalogs(session, monkeypatch):
    """MTG, Pokémon and Sorcery fixture catalogs, synced one source at a time."""
    monkeypatch.setenv("TCG_POKEMON_LANGUAGES", '["en", "fr", "ja"]')
    monkeypatch.setenv("TCG_POKEMON_KOREAN", "false")
    monkeypatch.setenv("TCG_POKEMON_CHINESE", "false")
    await register_games()

    tcgdex_data = TCGDEX_API | tcgdex_listings()
    pokemon_shared.clear()

    def tcgdex(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v2")
        return (
            httpx.Response(200, json=tcgdex_data[path])
            if path in tcgdex_data
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
        ("pokemon-asia", lambda r: r.get(url__startswith=TCGDEX).mock(side_effect=tcgdex)),
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
    # Printed only in Japanese: its name, translated in the interface language (English).
    assert (tropius["card"]["name"], tropius["card"]["translation"]) == ("トロピウス", "Tropius")
    assert (tropius["printings"][0]["name"], tropius["printings"][0]["translation"]) == (
        "トロピウス",
        "Tropius",
    )


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
    nonsense = await scan(client, alice, ocr("zzzz qqqq xxxx"))
    assert nonsense["candidates"] == [] and nonsense["status"] == "not_a_card"
    assert (await scan(client, alice, []))["candidates"] == []
    unknown = await client.post(
        "/api/scan/identify", json={"lines": [], "game": "chess"}, headers=alice
    )
    assert unknown.status_code == 404
    too_many = await client.post(
        "/api/scan/identify", json={"lines": [{"text": "x"}] * 201}, headers=alice
    )
    assert too_many.status_code == 422


async def test_unknown_card_is_fetched_from_its_source(client, session):
    from app.services import lookup
    from tests.test_mtg import RAW

    lookup._misses.clear()
    await register_games()
    await make_user(session)
    headers = await bearer(client, "alice")
    elves = next(c for c in RAW if c["set"] == "dom" and c["lang"] == "en")
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{SCRYFALL}/sets").respond(json=SETS)
        exact = router.get(f"{SCRYFALL}/cards/dom/168").respond(json=elves)
        router.get(f"{SCRYFALL}/cards/search").respond(
            json={"data": [c for c in RAW if c.get("oracle_id") == elves["oracle_id"]]}
        )
        missing = router.get(f"{SCRYFALL}/cards/war/999").respond(404)
        router.get(f"{SCRYFALL}/cards/named").respond(404)

        found = await scan(client, headers, ELVES_FR, "mtg")
        assert found["fetched"] is True and exact.call_count == 1
        assert found["candidates"][0]["card"]["name"] == "Llanowar Elves"
        assert found["candidates"][0]["printing_count"] == 1
        # Known now: no new lookup.
        assert (await scan(client, headers, ELVES_FR, "mtg"))["fetched"] is False

        unknown = ocr(
            "Nothing Like It",
            "Creature — Elf",
            "Flying",
            "2/2",
            "999/264 C",
            "WAR • EN",
            "™ & © 2019 Wizards of the Coast",
        )
        for _ in range(2):
            result = await scan(client, headers, unknown, "mtg")
            assert result["candidates"] == [] and result["fetched"] is False
            # A card, but not one the catalog or its source knows; what was read is sent.
            assert result["status"] == "not_found"
            assert result["detected"]["collector_number"] == "999"
        assert missing.call_count == 1  # misses are remembered
        assert found["status"] == "found"


async def test_unknown_sorcery_card_found_by_name(client, session):
    from app.services import lookup

    lookup._misses.clear()
    await register_games()
    await make_user(session)
    headers = await bearer(client, "alice")
    with respx.mock(assert_all_called=False) as router:
        router.get(SORCERY).respond(json=SORCERY_CARDS)
        found = await scan(client, headers, ABUNDANCE, "sorcery")
    assert found["fetched"] is True
    assert found["candidates"][0]["card"]["name"] == "Abundance"


async def test_printing_search(client, alice, session):
    from sqlalchemy import select

    from app.models import Card

    card_id = await session.scalar(select(Card.id).where(Card.name == "Abundance"))
    found = await client.get(f"/api/cards/{card_id}/printings", params={"q": "beta"}, headers=alice)
    assert [p["set"]["name"] for p in found.json()] == ["Beta"]
    every = (await client.get(f"/api/cards/{card_id}/printings", headers=alice)).json()
    assert len(every) == 2


def test_pokemon_parser_skips_asian_labels():
    provider = get_provider("pokemon")
    korean = provider.parse_ocr(
        ocr("서포트", "박사의 연구", "자신의 패를 모두 트래쉬하고", "SV1 F 190/198")
    )
    assert korean.name == "박사의 연구" and korean.lang == "ko"
    japanese = provider.parse_ocr(ocr("グッズ", "エネルギーつけかえ", "SV1a 060/073"))
    assert japanese.name == "エネルギーつけかえ" and japanese.lang == "ja"
    chinese = provider.parse_ocr(ocr("支援者", "博士的研究", "CSV1C 120/130"))
    assert chinese.name == "博士的研究"


async def test_identify_short_asian_name_in_noisy_text(client, alice):
    # No set or number, extra glyphs around the name: found by containment.
    lines = ocr("ーートロピウスのぎ", "リーフドレイン 20")
    result = await scan(client, alice, lines, "pokemon-asia")
    assert result["candidates"][0]["card"]["name"] in {"Tropius", "トロピウス"}


async def test_card_of_another_game_is_told_apart(client, alice):
    # An MTG card scanned with Pokémon chosen: not "not a card".
    result = await scan(client, alice, ELVES_FR, "pokemon")
    assert (result["status"], result["detected_game"]) == ("other_game", "mtg")
    # A Japanese Pokémon card scanned with the international game chosen: the Asia game's.
    result = await scan(client, alice, TROPIUS_JA, "pokemon")
    assert (result["status"], result["detected_game"]) == ("other_game", "pokemon-asia")
    # Sorcery chosen, a Sorcery card that is not in the catalog (no set code to tell).
    unknown = ocr(
        "Unknown Wanderer",
        "A Mortal Minion",
        "Genesis: draw a spell.",
        "Someone",
        "© 2025",
    )
    result = await scan(client, alice, unknown, "sorcery")
    assert result["status"] == "not_found"
    assert (await scan(client, alice, ocr("Exit", "Push"), "sorcery"))["status"] == "not_a_card"


def test_chinese_variants_and_script():
    from app.games.ocr import chinese_variants, script_language

    assert chinese_variants(["噴火龍"]) == ["噴火龍", "喷火龙"]
    assert chinese_variants(["喷火龙"]) == ["喷火龙", "噴火龍"]
    assert chinese_variants(["Lugia", "トロピウス"]) == ["Lugia", "トロピウス"]
    assert script_language(ocr("噴火龍")) == "zh-hant"
    assert script_language(ocr("喷火龙")) == "zh-hans"
    stage = get_provider("pokemon").parse_ocr(ocr("1阶进化", "火恐龙", "进化自 小火龙"))
    assert stage.name == "火恐龙"


def test_pokemon_parser_reads_mainland_chinese_set_codes():
    provider = get_provider("pokemon")
    for text, code in (
        ("151C 025/151", "151C"),
        ("CS5aC 120/130", "CS5aC"),
        ("CS4.5C 012/100", "CS4.5C"),
    ):
        hints = provider.parse_ocr(ocr("皮卡丘", text))
        assert (hints.set_code, hints.collector_number) == (code, text.split()[1].split("/")[0])


def test_pokemon_parser_reads_mega_evolution_cards():
    pokemon = get_provider("pokemon")
    clean = pokemon.parse_ocr(ocr("Stage 1", "Mega Camerupt ex", "HP 330", "I MEG EN 022/132"))
    assert (clean.name, clean.set_code, clean.lang, clean.collector_number) == (
        "Mega Camerupt ex",
        "MEG",
        "en",
        "022",
    )
    # "Mega" read as a line of its own.
    split = pokemon.parse_ocr(ocr("Mega", "Latias ex", "HP 300", "I MEG EN 100/132"))
    assert split.name == "Mega Latias ex"
    # Regulation mark glued to the set code, or to the code and language.
    glued = pokemon.parse_ocr(ocr("Mega Latias ex", "IMEG EN 100/132"))
    assert (glued.set_code, glued.lang, glued.collector_number) == ("MEG", "en", "100")
    packed = pokemon.parse_ocr(ocr("Mega Gallade ex", "ICRIEN 048/122"))
    assert (packed.set_code, packed.lang, packed.collector_number) == ("CRI", "en", "048")
    # O and I read for 0 and 1 in the number; letter prefixes stay.
    misread = pokemon.parse_ocr(ocr("Mega Mawile ex", "I MEG EN O94/132"))
    assert misread.collector_number == "094"
    assert pokemon.parse_ocr(ocr("Mega Latias ex", "MEG EN 1O0/l32")).collector_number == "100"
    assert pokemon.parse_ocr(ocr("Pikachu", "TG05/TG30")).collector_number == "TG05"
    # A four-letter code without a regulation mark letter in front stays whole.
    assert pokemon.parse_ocr(ocr("Pikachu", "G SVPX EN 001/010")).set_code == "SVPX"


def boxed(*rows: tuple[str, float]) -> list[OcrLine]:
    """Lines with their top position (fraction of the text box), as the app sends them."""
    return [OcrLine(text, 0.1, top) for text, top in rows]


def test_pokemon_parser_reported_scans():
    from app.games.pokemon.provider import CHINA, region_of

    pokemon = get_provider("pokemon")
    # The weakness "x2" sits in the bottom quarter above the code line: never the code.
    twm = pokemon.parse_ocr(
        boxed(("Amphinobi-ex PV 310", 0.05), ("x2", 0.8), ("H TWM FR 106/167", 0.95))
    )
    assert (twm.set_code, twm.lang, twm.collector_number) == ("TWM", "fr", "106")
    jtg = pokemon.parse_ocr(
        boxed(("Artikodin PV 120", 0.05), ("x2", 0.82), ("I JTG FR 032/159", 0.96))
    )
    assert (jtg.set_code, jtg.lang, jtg.collector_number) == ("JTG", "fr", "032")
    # Mainland card, code read in lower case, one Traditional-looking glyph: still China.
    cn = pokemon.parse_ocr(
        boxed(("尼多娜", 0.05), ("HP 90 宝可梦 進化", 0.1), ("x2", 0.8), ("151c 030/151", 0.95))
    )
    assert (cn.set_code, cn.lang, cn.collector_number) == ("151C", "zh-hans", "030")
    assert region_of(cn) == CHINA
    # Sword & Shield: no set code, the printed count and French words tell.
    asr = pokemon.parse_ocr(
        boxed(("Baudrive PV 70", 0.05), ("Faiblesse x2 Retraite", 0.8), ("F 063/189", 0.95))
    )
    assert (asr.set_code, asr.collector_number, asr.printed_total, asr.lang) == (
        None,
        "063",
        "189",
        "fr",
    )
    # Regulation mark glued to an Asian code, and the code glued to the number.
    for text, code in (("HSV6a 041/064", "HSV6a"), ("SV6a041/064", "SV6a")):
        sv6a = pokemon.parse_ocr(boxed(("ゾウドウ", 0.05), ("x2", 0.8), (text, 0.95)))
        assert (sv6a.set_code, sv6a.collector_number) == (code, "041")
    # Background text read below the card: the number is found above the bottom quarter.
    surfer = pokemon.parse_ocr(
        boxed(("Surfer", 0.05), ("Supporter", 0.1), ("SSP EN 187/191", 0.6), ("desk", 0.98))
    )
    assert surfer.collector_number == "187"
    # "PV" read in any case.
    assert pokemon.parse_ocr(ocr("Mewtwo", "pv 120", "x2")).lang == "fr"


def test_chinese_script_by_majority():
    from app.games.ocr import chinese_script

    # Mostly Simplified with one Traditional glyph read by mistake.
    assert chinese_script("尼多娜 宝可梦 进化 能量 進") == "zh-hans"
    assert chinese_script("尼多娜 寶可夢 進化 能量") == "zh-hant"
    # Shared characters only: Simplified (mainland) by default.
    assert chinese_script("尼多娜") == "zh-hans"


def test_stray_katakana_in_latin_text_is_not_japanese():
    from app.games.ocr import script_language

    # The Japanese model reads "O", "I" and "-" of a French card as ロ, エ and ー.
    french = ocr("Elfes de Llanowar", "Créature : elfe et druide", "ロ : Ajoutez エ.", "ー")
    assert script_language(french) is None
    assert get_provider("mtg").parse_ocr(french).lang == "fr"
    assert script_language(ocr("寛大なる者、アジャニ", "WAR • JP 184/264")) == "ja"


def test_mtg_parser_reported_scans():
    mtg = get_provider("mtg")
    # SPM 183 French foil: "L 0183" read "LO183", "SPM • FR" read "SPM AFR".
    lines = [
        ("Manoir Kravinoff", 0.07797271, 0.0),
        ("Terrain", 0.058479533, 0.561008),
        ("Ce terrain arrive engage.", 0.07212476, 0.63395226),
        ("-:Ajoutez", 0.05068226, 0.67639256),
        ("ou", 0.38791424, 0.6777188),
        ("4, c:", 0.056530215, 0.71750665),
        ("Surveillez 1. (Regardez la carte du", 0.21637426, 0.7188329),
        ("dessus de votre bibliöthèquc. louspouves la", 0.054580897, 0.75596815),
        ("mettre dans vore", 0.064327486, 0.79045093),
        ("GinLLlieru.)", 0.41520467, 0.7944297),
        ("Des trophées exotiques de chasses victorieuses", 0.064327486, 0.8567639),
        ("ornent les murs du Domaine des Kravinoff.", 0.046783626, 0.89257294),
        ("MARVi.", 0.9025341, 0.96153843),
        ("IM&2025 Wvads of the", 0.61208576, 0.9761273),
        ("(Cst", 0.9356725, 0.9814324),
        ("LO183", 0.0, 0.9535809),
        ("SPM AFR DAYID AIYARIZ", 0.01754386, 0.969496),
    ]
    hints = mtg.parse_ocr([OcrLine(text, left, top) for text, left, top in lines])
    assert (hints.name, hints.set_code, hints.collector_number, hints.lang) == (
        "Manoir Kravinoff",
        "SPM",
        "183",
        "fr",
    )
    # A real code is still taken over a word stuck to it.
    assert mtg.parse_ocr(ocr("Forest", "0280 L", "BLB • EN Artist")).set_code == "BLB"


def test_mtg_type_words_tell_latin_languages_apart():
    mtg = get_provider("mtg")

    def lang(*texts: str) -> str | None:
        return mtg.parse_ocr(ocr("Name", *texts, "™ & © 2008 Wizards of the Coast")).lang

    assert lang("Creature : Elfe", "Quand le terrain arrive") == "fr"
    assert lang("Kreatur — Elf Druide") == "de"
    assert lang("Criatura — Elfo", "Conjuro") == "es"
    assert lang("Criatura — Elfo", "Feitiço") == "pt"
    assert lang("Criatura — Elfo") is None  # Spanish or Portuguese: the name tells
    assert lang("Creatura — Elfo") == "it"
    # "creature" is French too (accent missed): the name tells.
    assert lang("Creature — Elf Druid", "Target creature gets +1/+1.") is None
    assert lang("Instant", "Destroy target artifact.") == "en"


async def test_identify_language_from_the_name(client, alice):
    # Old frame: no "DOM • FR"; the French name says the language.
    french = await scan(client, alice, ocr("Elfes de Llanowar", "168/269"), game="mtg")
    assert french["candidates"][0]["card"]["name"] == "Llanowar Elves"
    assert french["detected"]["lang"] == "fr"
    german = await scan(client, alice, ocr("Llanowarelfen"), game="mtg")
    assert german["detected"]["lang"] == "de"
    english = await scan(client, alice, ocr("Llanowar Elves"), game="mtg")
    assert english["detected"]["lang"] == "en"


def test_mtg_parser_split_name_and_glued_language():
    mtg = get_provider("mtg")

    def parse(lines):
        return mtg.parse_ocr([OcrLine(text, left, top) for text, left, top in lines])

    # TDM 269 French: the name read in two pieces, "TDM • FR" stuck to the artist.
    thornwood = parse(
        [
            ("Chutes de", 0.044315994, 0.0),
            ("Boisépine", 0.31984586, 0.0013020834),
            ("Terrain", 0.0327553, 0.56640625),
            ("Ce terrain arrive engagé.", 0.048169557, 0.63671875),
            ("Quand ce terrain arrive, VOus gagnez 1 point", 0.048169557, 0.68619794),
            ("de vie.", 0.046242774, 0.71875),
            ("-:Ajoutez ou &.", 0.040462427, 0.7604167),
            ("Au matin, la seule trace du conflit opposant les", 0.038535647, 0.8255208),
            ("chasseurs temuriens et les", 0.030828517, 0.859375),
            ("éclaireurs sultat était", 0.53757226, 0.85807294),
            ("des étendards abandonnés dans la neige fraîche.", 0.04238921, 0.8880208),
            ("M& C 2025 \\Wizards of the Coast", 0.62813103, 0.9583333),
            ("TDM FRALEXANDER OSTROWSKI", 0.0057803467, 0.9713542),
            ("L", 0.0, 0.9609375),
        ]
    )
    assert (thornwood.name, thornwood.set_code, thornwood.lang) == (
        "Chutes de Boisépine",
        "TDM",
        "fr",
    )
    assert "Chutes de" in thornwood.other_names
    # CMM 408 French: "CMM • FR" stuck to "JAMES PAICK"; the mana cost is not the name.
    scytheclaw = parse(
        [
            ("5", 0.94056845, 0.015734266),
            ("Griffe faucheuse", 0.04909561, 0.0),
            ("Artefact: equipement", 0.04134367, 0.5629371),
            ("Arme vvante (Oiuand cet èquipenent arrive sur le", 0.033591732, 0.6451049),
            ("La créature équipée gagne +1/+1.", 0.03875969, 0.73426574),
            ("Equipement 3", 0.03875969, 0.8986014),
            ("i&", 0.6098191, 0.96503496),
            ("302TWzarts of the Cust", 0.70284235, 0.9632867),
            ("CMMFRAMES PAICK", 0.0, 0.9807692),
            ("R", 0.0, 0.96153843),
            ("0408", 0.03617571, 0.9597902),
        ]
    )
    assert (
        scytheclaw.name,
        scytheclaw.set_code,
        scytheclaw.collector_number,
        scytheclaw.lang,
    ) == ("Griffe faucheuse", "CMM", "408", "fr")
    # Capitals that only look like a code and a language are not taken.
    assert mtg.parse_ocr(ocr("Forest", "Illus. FRANK FRAZETTA")).set_code is None


async def _mtg_printing(session, set_code: str, number: str):
    from sqlalchemy import select

    from app.models import CardSet, Printing

    session.expire_all()
    return await session.scalar(
        select(Printing)
        .join(CardSet)
        .where(CardSet.game_id == "mtg", CardSet.external_id == set_code)
        .where(Printing.external_id == number)
    )


async def test_identify_set_code_without_number(client, session, alice):
    from app.models import Printing

    card_id = (await _mtg_printing(session, "dom", "168")).card_id
    war_id = (await _mtg_printing(session, "war", "184★")).set_id
    # A newer reprint, in French too: first by date, but the code read says DOM.
    session.add(
        Printing(
            card_id=card_id,
            set_id=war_id,
            external_id="999",
            collector_number="999",
            finishes=["nonfoil"],
            languages=["en", "fr"],
        )
    )
    await session.commit()
    lines = ocr("Elfes de Llanowar", "Créature : elfe et druide", "DOM • FR Chris Rahn")
    result = await scan(client, alice, lines, game="mtg")
    assert result["detected"]["set_code"] == "DOM"
    first = result["candidates"][0]["printings"][0]
    assert (first["set"]["code"], first["collector_number"]) == ("DOM", "168")


async def test_missing_language_is_offered_and_learned(client, session, alice):
    from sqlalchemy import update

    from app.models import Printing

    elves = await _mtg_printing(session, "dom", "168")
    elves_id, set_id, card_id = elves.id, elves.set_id, elves.card_id
    # Sources know no French Llanowar Elves in DOM, nor any French card of DOM.
    await session.execute(update(Printing).where(Printing.id == elves_id).values(languages=["en"]))
    await session.commit()
    result = await scan(client, alice, ELVES_FR, game="mtg")
    assert result["candidates"][0]["printings"][0]["languages"] == ["en"]

    # Another DOM card is known in French: the set was printed in French.
    session.add(
        Printing(
            card_id=card_id,
            set_id=set_id,
            external_id="168p",
            collector_number="168p",
            finishes=["nonfoil"],
            languages=["en", "fr"],
        )
    )
    await session.commit()
    result = await scan(client, alice, ELVES_FR, game="mtg")
    printing = result["candidates"][0]["printings"][0]
    assert printing["id"] == elves_id and printing["languages"] == ["en", "fr"]

    # Adding a French copy records the language on the printing.
    response = await client.post(
        "/api/collection/adjust",
        json={"printing_id": elves_id, "finish": "nonfoil", "language": "fr", "delta": 1},
        headers=alice,
    )
    assert response.status_code == 200, response.text
    assert (await _mtg_printing(session, "dom", "168")).languages == ["en", "fr"]
    # A language the set has no card in is stored on the copy only.
    await client.post(
        "/api/collection/adjust",
        json={"printing_id": elves_id, "finish": "nonfoil", "language": "ko", "delta": 1},
        headers=alice,
    )
    assert (await _mtg_printing(session, "dom", "168")).languages == ["en", "fr"]
