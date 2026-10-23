"""Games split by market (Pokémon international / Asia / China, Yu-Gi-Oh! TCG / OCG)."""

from app.core.config import get_settings
from app.games.base import OcrHints, group_of, picture_game
from app.games.pokemon.provider import ASIA, CHINA, INTERNATIONAL, PokemonSettings, region_of
from app.games.yugioh.provider import YugiohSettings
from app.services.schedule import worker_games
from tests.conftest import bearer, make_user
from tests.test_collection import import_file
from tests.test_split import _card, _printing, _set


async def test_games_list_their_group(client, session):
    await make_user(session)
    headers = await bearer(client, "alice")
    games = {g["id"]: g for g in (await client.get("/api/games", headers=headers)).json()}
    shown = {
        g: (games[g]["group"], games[g]["group_name"], games[g]["region_label"])
        for g in ("pokemon", "pokemon-asia", "pokemon-china", "yugioh", "yugioh-ocg", "mtg")
    }
    assert shown == {
        "pokemon": ("pokemon", "Pokémon", "International"),
        "pokemon-asia": ("pokemon", "Pokémon", "Asia"),
        "pokemon-china": ("pokemon", "Pokémon", "China"),
        "yugioh": ("yugioh", "Yu-Gi-Oh!", "TCG"),
        "yugioh-ocg": ("yugioh", "Yu-Gi-Oh!", "OCG"),
        "mtg": ("mtg", "Magic: The Gathering", None),
    }
    assert games["pokemon-asia"]["languages"] == ["ja", "ko", "zh-hant", "th", "id"]
    assert games["pokemon-china"]["has_prices"] is False
    assert games["yugioh-ocg"]["languages"] == ["ja", "ko", "zh-hans", "zh-hant", "en"]
    # The games of a group are listed together.
    ids = list(games)
    assert ids.index("pokemon-china") - ids.index("pokemon") == 2
    assert (group_of("yugioh-ocg"), picture_game("pokemon-china"), picture_game("mtg")) == (
        "yugioh",
        "pokemon",
        "mtg",
    )


def test_worker_games_expand_a_group_listed_alone(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "worker_games", ["pokemon", "mtg"])
    assert worker_games() == ["pokemon", "pokemon-asia", "pokemon-china", "mtg"]
    monkeypatch.setattr(settings, "worker_games", ["pokemon", "pokemon-asia"])
    assert worker_games() == ["pokemon", "pokemon-asia"]
    monkeypatch.setattr(settings, "worker_games", ["yugioh-ocg"])
    assert worker_games() == ["yugioh-ocg"]


def test_language_settings_of_before_the_split(monkeypatch):
    # One list for every market (0.16.0): its Asian languages are the Asia game's.
    monkeypatch.setenv("TCG_POKEMON_LANGUAGES", '["en", "fr", "ja", "zh-tw"]')
    assert PokemonSettings().tcgdex_languages() == {"en", "fr", "ja", "zh-tw"}
    monkeypatch.setenv("TCG_POKEMON_ASIA_LANGUAGES", '["ja", "zh-hant"]')
    monkeypatch.setenv("TCG_POKEMON_LANGUAGES", '["en"]')
    assert PokemonSettings().tcgdex_languages() == {"en", "ja", "zh-tw"}
    monkeypatch.delenv("TCG_POKEMON_ASIA_LANGUAGES")
    assert PokemonSettings().tcgdex_languages() == {"en", "ja", "zh-tw", "th", "id"}

    monkeypatch.setenv("TCG_YUGIOH_LANGUAGES", '["en", "fr", "ja"]')
    settings = YugiohSettings()
    assert (settings.tcg(), settings.ocg()) == (["en", "fr"], ["ja", "en"])
    monkeypatch.setenv("TCG_YUGIOH_OCG_LANGUAGES", '["ko"]')
    assert YugiohSettings().ocg() == ["ko"]


def test_pokemon_market_of_a_scanned_card():
    def market(set_code=None, lang=None):
        return region_of(OcrHints(set_code=set_code, lang=lang))

    assert market("PAL", "en") == market(None, "fr") == market() == INTERNATIONAL
    assert market("SV1a", "ja") == market(None, "ko") == market(None, "th") == ASIA
    # Taiwan prints Japanese set codes; mainland China "…C" codes.
    assert market("SV1a", "zh-hans") == market(None, "zh-hant") == ASIA
    assert market("CSV1C", "zh-hans") == market("151C") == market(None, "zh-hans") == CHINA


async def test_csv_of_before_the_split_finds_the_asian_printing(client, session):
    from app.main import register_games

    await register_games()
    card_set = await _set(session, "pokemon-asia", "SV1a", "SV1a", "ja")
    card = await _card(session, "pokemon-asia", "ja:トロピウス", {"ja": "トロピウス"})
    await _printing(session, card, card_set, "001", ["ja"])
    await make_user(session)
    await session.commit()
    headers = await bearer(client, "alice")
    text = (
        "game,set_code,collector_number,name,language,finish,condition,quantity\n"
        "pokemon,SV1a,001,トロピウス,ja,normal,NM,2\n"
    )
    report = (await import_file(client, headers, text)).json()
    assert (report["imported"], report["errors"]) == (1, [])
    items = (await client.get("/api/collection", headers=headers)).json()["items"]
    assert [(i["quantity"], i["language"]) for i in items] == [(2, "ja")]
