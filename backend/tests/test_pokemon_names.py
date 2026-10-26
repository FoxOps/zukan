"""Asian Pokémon card names in the reader's language: card names table (Trainers, Energies,
Pokémon named with other words) and international names of the English card."""

import httpx
import respx

from app.games.base import CardData
from app.games.pokemon import shared
from app.games.pokemon.asia import korean_card
from app.games.pokemon.official_asia import OfficialCard, to_card
from app.games.pokemon.provider import translate_latin
from app.games.pokemon.species import basic_energy, card_translations, english_name
from app.services.display import ShownName, pick_name


def test_table_names_trainers_and_pokemon_with_other_words():
    assert english_name("보스의 지령", "ko") == "Boss's Orders"
    assert english_name("ボスの指令", "ja") == "Boss's Orders"
    assert english_name("老大的指令", "zh-hant") == "Boss's Orders"
    assert english_name("ナンジャモ", "ja") == "Iono"
    # Line breaks and spacing of the sources do not matter.
    assert english_name("로켓단의  뮤츠\nex", "ko") == "Team Rocket's Mewtwo ex"
    assert english_name("모르는 카드", "ko") is None


def test_basic_energies():
    assert basic_energy("기본 불꽃 에너지") == "Fire Energy"
    assert basic_energy("기본 물   에너지") == "Water Energy"
    assert basic_energy("基本闘エネルギー") == "Fighting Energy"
    assert basic_energy("基本【惡】能量") == "Darkness Energy"
    assert basic_energy("レガシーエネルギー") is None
    assert english_name("基本フェアリーエネルギー", "ja") == "Fairy Energy"


def test_card_translations():
    # Species names first: every language.
    names = card_translations("피카츄", "ko", [25])
    assert names["en"] == "Pikachu" and names["fr"] == "Pikachu" and names["ja"] == "ピカチュウ"
    # Not species names only: English from the table.
    assert card_translations("로켓단의 뮤츠 ex", "ko", [150]) == {"en": "Team Rocket's Mewtwo ex"}
    # Trainers: never species names ("모야모" holds no Pokémon), the table only.
    assert card_translations("모야모", "ko", [], pokemon=False) == {"en": "Iono"}
    # International names: no table.
    assert card_translations("Boss's Orders", "en", [], pokemon=False) == {}


def test_korean_dataset_trainer_named_in_english():
    raw = {"name": "보스의 지령", "number": "070", "card_type": "서포트", "author": ["NC Empire"]}
    card = korean_card(raw, "SV1a")
    assert card is not None
    assert card.names == {"ko": "보스의 지령", "en": "Boss's Orders"}
    assert card.attributes == {"category": "Trainer", "trainerType": "Supporter"}


def test_official_korean_trainer_named_in_english():
    listed = OfficialCard(code="SV1a", number="070", image=None, name="보스의 지령")
    card = to_card(listed, "ko", "x")
    assert card.names == {"ko": "보스의 지령", "en": "Boss's Orders"}
    # Thai Trainers: no table.
    thai = to_card(OfficialCard(code="SV1a", number="070", image=None, name="คำสั่งบอส"), "th", "x")
    assert thai.names == {"th": "คำสั่งบอส"}


def test_translate_latin_adds_international_names():
    latin = {"en:boss's orders": {"fr": "Ordres du Boss", "de": "Befehl vom Boss"}}
    names = {"ko": "보스의 지령", "en": "Boss’s Orders"}
    card = CardData(external_id="ko:보스의 지령", name="보스의 지령", names=names)
    translate_latin(card, latin)
    assert card.names["fr"] == "Ordres du Boss" and card.names["de"] == "Befehl vom Boss"
    assert card.names["ko"] == "보스의 지령"
    # Names already there (species names) stay.
    card = CardData(external_id="x", name="x", names={"en": "Boss's Orders", "fr": "Mine"})
    assert translate_latin(card, latin).names["fr"] == "Mine"
    # No English name: unchanged.
    card = CardData(external_id="y", name="y", names={"ko": "모르는 카드"})
    assert translate_latin(card, latin).names == {"ko": "모르는 카드"}


async def test_international_listings_give_latin_names():
    api = "https://tcgdex.test/v2"
    listings = {
        "/en/sets": [{"id": "sv01"}, {"id": "A1"}],
        "/en/series/tcgp": {"sets": [{"id": "A1"}]},
        "/en/cards": [
            {"id": "sv01-172", "name": "Boss's Orders"},
            {"id": "swsh2-154", "name": "Boss's Orders"},
            {"id": "A1-1", "name": "Bulbasaur"},
        ],
        "/fr/cards": [
            {"id": "sv01-172", "name": "Ordres du Boss"},
            {"id": "swsh2-154", "name": "Ordres du Boss"},
            {"id": "A1-1", "name": "Bulbizarre"},
        ],
        "/de/cards": [{"id": "swsh2-154", "name": "Befehl vom Boss"}],
    }

    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v2")
        if path in listings:
            return httpx.Response(200, json=listings[path])
        return httpx.Response(404, json={})

    with respx.mock() as router:
        router.get(url__startswith=api).mock(side_effect=respond)
        async with httpx.AsyncClient() as http:
            known = await shared._read(http, api, {"tcgp"})
    boss = known.latin_names["en:boss's orders"]
    assert boss == {"fr": "Ordres du Boss", "de": "Befehl vom Boss"}
    # Digital cards (Pokémon TCG Pocket) are left out.
    assert "en:bulbasaur" not in known.latin_names


def test_korean_card_reads_in_the_interface_language():
    names = {"ko": "보스의 지령", "en": "Boss's Orders", "fr": "Ordres du Boss"}
    assert pick_name(names, "fr", latin=False, set_lang="ko") == ShownName(
        "보스의 지령", "Ordres du Boss"
    )
    assert pick_name(names, "de", latin=False, set_lang="ko") == ShownName(
        "보스의 지령", "Boss's Orders"
    )
