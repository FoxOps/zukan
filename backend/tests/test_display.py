from datetime import date
from types import SimpleNamespace

from app.services.display import ShownName, card_is_latin, latest_lang, pick_image, pick_name
from app.services.scripts import is_latin, ordered, printing_is_latin

_ids = iter(range(1, 1000))


def printing(set_lang, released=None, images=(), languages=None, number="1"):
    return SimpleNamespace(
        id=next(_ids),
        set=SimpleNamespace(lang=set_lang, release_date=released),
        languages=list(languages if languages is not None else [set_lang]),
        image_urls={lang: f"https://img/{lang}" for lang in images},
        image_paths={},
        collector_number=number,
    )


def test_scripts():
    assert is_latin("fr") and is_latin("pt") and not is_latin("ja")
    assert not is_latin("zh-hans") and not is_latin("ru") and not is_latin("ko")
    assert ordered(["zh-hans", "ru", "ja", "fr", "en", "nl"]) == [
        "en", "fr", "ja", "zh-hans", "ru", "nl",
    ]  # fmt: skip
    # Sets without a language (Magic): non-Latin only when every language is.
    assert printing_is_latin(printing(None, languages=["en", "ja"]))
    assert not printing_is_latin(printing(None, languages=["ja"]))
    assert not printing_is_latin(printing("ru"))


def test_latin_card_language_first_then_latest_printing():
    old_fr = printing("fr", date(2021, 1, 1), ["fr"])
    new_en = printing("en", date(2025, 1, 1), ["en"])
    jp = printing("ja", date(2026, 1, 1), ["ja"])
    printings = [old_fr, new_en, jp]
    assert card_is_latin(printings)
    # French UI: the language wins over the newest printing.
    assert pick_image(printings, "fr", True) == (old_fr, "fr")
    # German UI, no German image: English, never the newer Japanese one.
    assert pick_image(printings, "de", True) == (new_en, "en")
    # No Latin image at all: the first available language.
    assert pick_image([jp], "fr", True) == (jp, "ja")


def test_multi_language_printing_before_newer_single_language_one():
    # Magic: a newer English-only Secret Lair would hide the card's translations.
    core = printing(None, date(2021, 1, 1), ["en"], languages=["en", "fr", "de", "ja"])
    secret_lair = printing(None, date(2025, 1, 1), ["en"], languages=["en"])
    assert pick_image([secret_lair, core], "en", True) == (core, "en")
    # Only single-language printings: the newest.
    other = printing(None, date(2019, 1, 1), ["en"], languages=["en"])
    assert pick_image([other, secret_lair], "en", True) == (secret_lair, "en")


def test_latest_then_first_then_undated():
    undated = printing("fr", None, ["fr"])
    first = printing("fr", date(1999, 1, 1), ["fr"])
    latest = printing("fr", date(2023, 1, 1), ["fr"])
    no_image = printing("fr", date(2026, 1, 1))
    assert pick_image([undated, first, latest, no_image], "fr", True) == (latest, "fr")
    assert pick_image([undated, first], "fr", True) == (first, "fr")
    assert pick_image([undated], "fr", True) == (undated, "fr")
    assert pick_image([no_image], "fr", True) is None


def test_non_latin_card_image():
    ja = printing("ja", date(2023, 1, 1), ["ja", "en"])
    ko = printing("ko", date(2024, 1, 1), ["ko"])
    assert not card_is_latin([ja, ko])
    assert latest_lang([ja, ko]) == "ko"
    # UI language if non-Latin, then the set's language, then the first non-Latin one.
    assert pick_image([ja, ko], "ja", False, "ko") == (ja, "ja")
    assert pick_image([ja, ko], "fr", False, "ko") == (ko, "ko")
    assert pick_image([ja, ko], "fr", False, "th") == (ja, "ja")
    # Only an English image: English before anything else.
    en_only = printing("ja", date(2023, 1, 1), ["en"])
    assert pick_image([en_only], "fr", False, "ja") == (en_only, "en")


def test_names():
    names = {"en": "Weedle", "fr": "Aspicot", "ja": "ビードル", "ko": "뿔충이"}
    # Latin card: UI language, then English, then the first available language.
    assert pick_name(names, "fr", True) == ShownName("Aspicot")
    assert pick_name(names, "nl", True) == ShownName("Weedle")
    assert pick_name({"ja": "ビードル"}, "fr", True) == ShownName("ビードル")
    assert pick_name({}, "fr", True, default="Weedle") == ShownName("Weedle")
    # Non-Latin card: "Name (Translation)".
    assert pick_name(names, "fr", False, "ja") == ShownName("ビードル", "Aspicot")
    assert pick_name(names, "nl", False, "ko") == ShownName("뿔충이", "Weedle")
    assert pick_name(names, "ja", False, "ko") == ShownName("ビードル", "Weedle")
    assert pick_name(names, "fr", False, "th") == ShownName("ビードル", "Aspicot")
    # No Latin name, or the same text: the name alone.
    assert pick_name({"ja": "ポケモンだいすきクラブ"}, "fr", False, "ja") == ShownName(
        "ポケモンだいすきクラブ"
    )
    assert pick_name({"ja": "N", "en": "N"}, "fr", False, "ja") == ShownName("N")
    # Russian is not Latin.
    assert pick_name({"ru": "Шок", "en": "Shock"}, "fr", False, "ru") == ShownName("Шок", "Shock")


def test_non_latin_name_on_latin_card_gets_translation():
    # Latin card read in a non-Latin UI language (Riftbound Simplified Chinese names).
    names = {"en": "Ahri, Alluring", "zh-hans": "阿狸，魅惑"}
    assert pick_name(names, "zh-hans", True) == ShownName("阿狸，魅惑", "Ahri, Alluring")
    assert pick_name(names, "ko", True) == ShownName("Ahri, Alluring")
    # Only a non-Latin name known: shown alone.
    assert pick_name({"zh-hans": "能量转移"}, "fr", True) == ShownName("能量转移")
