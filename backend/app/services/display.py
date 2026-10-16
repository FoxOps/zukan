"""Which image and name show a card or a printing.

Latin and mixed cards (at least one printing in a Latin-script set):
  image language: UI language > English > first available language;
  name: UI language > English > first available language.
Non-Latin cards (every printing in a non-Latin set, see `scripts`):
  image language: UI language if non-Latin > set language > first available non-Latin
  language > English > first available language;
  name: "Name (Translation)", the name in the UI language if non-Latin > set language >
  first available non-Latin language.
Any name shown in a non-Latin script (a non-Latin card, or a non-Latin UI language on a
Latin card) carries a translation: the name in the UI language if Latin > English > first
available Latin language (dropped when missing or identical).
The language comes first, then the printing having an image in it: latest set, else
first, else any (undated sets last). No image at all: a placeholder (None).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from app.models import Printing
from app.services import images
from app.services.scripts import is_latin, ordered, printing_is_latin, printing_lang


@dataclass(frozen=True)
class ShownName:
    name: str
    # Latin name next to a non-Latin one ("ビードル (Aspicot)").
    translation: str | None = None


def card_is_latin(printings: Iterable[Printing]) -> bool:
    printings = list(printings)
    return not printings or any(printing_is_latin(p) for p in printings)


def latest_lang(printings: Iterable[Printing]) -> str | None:
    """Language of the newest set among `printings`."""
    newest = sorted(printings, key=_age)
    return printing_lang(newest[0]) if newest else None


def _age(printing: Printing) -> tuple[bool, date, str]:
    """Sort key: latest set first, undated sets last."""
    released = printing.set.release_date
    return (released is None, -(released or date.min).toordinal(), printing.collector_number or "")


def _first(chain: Iterable[str | None], available: Iterable[str]) -> str | None:
    found = set(available)
    return next((lang for lang in chain if lang in found), None)


def _image_chain(available: Iterable[str], ui_lang: str, latin: bool, set_lang: str | None):
    langs = ordered(available)
    if latin:
        return [ui_lang, "en", *langs]
    non_latin = [lang for lang in langs if not is_latin(lang)]
    return [None if is_latin(ui_lang) else ui_lang, set_lang, *non_latin, "en", *langs]


def pick_image(
    printings: Sequence[Printing], ui_lang: str, latin: bool, set_lang: str | None = None
) -> tuple[Printing, str] | None:
    """The printing and language whose image shows the card (sets must be loaded)."""
    by_lang: dict[str, list[Printing]] = {}
    for printing in sorted(printings, key=_age):
        for lang in images.image_languages(printing):
            # An empty path: the image server refused that download.
            if printing.image_paths.get(lang) != "":
                by_lang.setdefault(lang, []).append(printing)
    lang = _first(_image_chain(by_lang, ui_lang, latin, set_lang), by_lang)
    return (by_lang[lang][0], lang) if lang else None


def pick_name(
    names: Mapping[str, str],
    ui_lang: str,
    latin: bool,
    set_lang: str | None = None,
    default: str = "",
) -> ShownName:
    """`names` maps languages to names; `default` (canonical name) when none fits."""
    langs = ordered(names)
    latin_langs = [lang for lang in langs if is_latin(lang)]
    non_latin = [lang for lang in langs if not is_latin(lang)]
    lang = None
    if not latin:
        lang = _first([None if is_latin(ui_lang) else ui_lang, set_lang, *non_latin], non_latin)
    if lang is None:
        lang = _first([ui_lang, "en", *langs], langs)
    if lang is None:
        return ShownName(default)
    if is_latin(lang):
        return ShownName(names[lang])
    # Every name in a non-Latin script gets its Latin translation, whatever chose it.
    other = _first([ui_lang if is_latin(ui_lang) else None, "en", *latin_langs], latin_langs)
    translation = names[other] if other else None
    return ShownName(names[lang], translation if translation != names[lang] else None)
