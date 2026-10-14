"""Writing systems of card languages.

Cards printed only in non-Latin scripts (Japanese, Korean, Chinese, Thai, Cyrillic…) are
shown by their own name with a Latin translation next to it; every other card is shown
in the reader's language (see `display`).
"""

from collections.abc import Iterable

from app.models import Printing

# Base language codes (before any "-region" part) not written in the Latin alphabet.
NON_LATIN = frozenset(
    {"ja", "ko", "zh", "th", "ru", "uk", "be", "bg", "sr", "mk", "el", "grc", "ar", "fa",
     "he", "hi", "sa", "ph"}
)  # fmt: skip
# "First available language" order; other languages follow alphabetically.
LANG_ORDER = ("en", "fr", "de", "it", "es", "pt", "ja", "ko", "zh-hant", "zh-hans", "th", "ru")
_RANK = {lang: rank for rank, lang in enumerate(LANG_ORDER)}


def is_latin(lang: str) -> bool:
    return lang.split("-")[0].casefold() not in NON_LATIN


def ordered(langs: Iterable[str]) -> list[str]:
    """`langs` in "first available language" order, without duplicates."""
    return sorted(set(langs), key=lambda lang: (_RANK.get(lang, len(LANG_ORDER)), lang))


def printing_lang(printing: Printing) -> str | None:
    """Language of the printing's set: the set's own, else (sets printed in several
    languages, e.g. Magic) the printing's first language, preferring its script."""
    if printing.set.lang:
        return printing.set.lang
    langs = ordered(printing.languages)
    non_latin = [lang for lang in langs if not is_latin(lang)]
    if langs and len(non_latin) == len(langs):
        return non_latin[0]
    return next((lang for lang in langs if is_latin(lang)), None)


def printing_is_latin(printing: Printing) -> bool:
    """A set is non-Latin when its language is, or (no set language) when every language
    of the printing is."""
    lang = printing_lang(printing)
    return lang is None or is_latin(lang)
