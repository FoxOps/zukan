"""Pokémon TCG, data from TCGdex (https://tcgdex.dev), as three games, one per publisher
and market (`REGIONS`):
- Pokémon TCG (The Pokémon Company International): English, French, German, Italian,
  Spanish, Portuguese.
- Pokémon TCG Asia (The Pokémon Company, Japan): Japanese, Korean, Traditional Chinese,
  Thai, Indonesian.
- Pokémon TCG China (The Pokémon Company China): Simplified Chinese.

TCGdex has no bulk export, so card details are fetched one by one:
- English sets: every card in full (types, rarity, variants, Cardmarket prices).
- Other languages: a set id listed in several languages is one set (international
  sets share English ids, Asian sets share ids between Japanese, Korean and Traditional
  Chinese). A few Japanese sets reuse an international id for other cards (Japanese "neo2"
  is not Neo Discovery): they are stored as `asia:<id>` (`shared.py` lists those ids).
  Its base language (English, else Japanese, Traditional Chinese, Thai, Indonesian) is
  fetched in full; the other listings only add printed names and images (partial data).
- Korean and Simplified Chinese come from open datasets (`asia.py`): TCGdex has almost
  no Korean cards and lists the mainland Chinese sets without cards. Korean sets join
  the Asian set of the same id (Korean "M2" is Japanese "M2") by collector number,
  others are sets of their own. Mainland Chinese sets make the China game.

Pokémon has no card id shared across printings; printings are grouped by name. Names
made of species names (`species.py`) are known in every language, so Asian printings
of "ルギアV" join the English "Lugia V" card. Other cards stay grouped per language.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.http import get_with_retry
from app.games.base import (
    CardData,
    CardRef,
    CatalogBatch,
    ColorDef,
    FilterDef,
    FinishDef,
    OcrHints,
    OcrLine,
    PriceQuote,
    PriceTarget,
    PrintingData,
    PrintingRef,
    RarityDef,
    SetData,
)
from app.games.ocr import bottom_part, by_position, clean, letter_ratio, script_language
from app.games.pokemon import asia, official_asia, official_jp, shared
from app.games.pokemon.species import (
    LATIN_LANGUAGES,
    card_translations,
    normalize_name,
    species_names,
)
from app.games.pokemon.types import NO_TYPE, card_colors
from app.models import Printing

log = logging.getLogger(__name__)

API_URL = "https://api.tcgdex.net/v2"
# Symbols drawn for Zukan (scripts/draw_color_symbols.py).
SYMBOLS = Path(__file__).parent / "symbols"
LEGAL_NOTICE = (
    "Pokémon is a trademark of Nintendo, Creatures Inc. and GAME FREAK inc.; the card game "
    "is published by The Pokémon Company. Zukan is not produced, endorsed, supported or "
    "affiliated with Nintendo, Creatures, GAME FREAK or The Pokémon Company. Card data from "
    "TCGdex, the Pokémon TCG API data, PTCG-database and PTCG-CHS-Datasets."
)
CONCURRENCY = 8
# Series that are not physical cards (Pokémon TCG Pocket is a mobile game).
DIGITAL_SERIES = {"tcgp"}
# Energy type symbols of the official card database (pokemon.com), 25 px each.
ENERGY_SPRITE = "https://assets.pokemon.com/static2/_ui/img/cards/energy-types.png"

# TCGdex language codes to ours.
LANGUAGES = {
    "en": "en",
    "fr": "fr",
    "de": "de",
    "it": "it",
    "es": "es",
    "pt": "pt",
    "ja": "ja",
    "ko": "ko",
    "zh-cn": "zh-hans",
    "zh-tw": "zh-hant",
    "th": "th",
    "id": "id",
}
# Base language order for sets listed in several languages (zh-cn data partly comes in
# Traditional characters, so it comes last).
BASE_ORDER = ["en", "fr", "de", "it", "es", "pt", "ja", "ko", "zh-tw", "th", "id", "zh-cn"]
ASIAN = {"ja", "ko", "zh-tw", "zh-cn", "th", "id"}
# Read from TCGdex by default. Korean and Simplified Chinese come from `asia.py`
# (TCGdex has 239 Korean cards and empty mainland Chinese sets).
DEFAULT_LANGUAGES = ["en", "fr", "de", "it", "es", "pt"]
DEFAULT_ASIA_LANGUAGES = ["ja", "zh-tw", "th", "id"]
# Our spelling of a TCGdex language, accepted in settings ("zh-hant" for "zh-tw").
_SETTING_ALIASES = {ours: theirs for theirs, ours in LANGUAGES.items()}
# Prefix of Asian sets whose TCGdex id is also an international set's.
ASIAN_PREFIX = "asia:"
VARIANTS = {
    "normal": "normal",
    "holo": "holo",
    "reverse": "reverse",
    "firstEdition": "first_edition",
}


class PokemonSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TCG_POKEMON_", env_file=".env", extra="ignore")

    # TCGdex languages of the international game. Asian languages listed here (one game
    # had them all before 0.17.0) are the Asia game's when `asia_languages` is not set.
    languages: list[str] = DEFAULT_LANGUAGES
    # TCGdex languages of the Asia game (~40k cards fetched one by one).
    asia_languages: list[str] | None = None
    # Korean cards (Asia game) from type-null/PTCG-database, Simplified Chinese ones
    # (China game) from duanxr/PTCG-CHS-Datasets (see asia.py).
    korean: bool = True
    chinese: bool = True
    # Pictures of Japanese printings TCGdex lacks, from the official Japanese card search
    # (official_jp.py), at most this many requests a day.
    official_jp: bool = True
    official_jp_daily_requests: int = 300
    # Thai, Indonesian, Traditional Chinese and Korean cards from the official Asian card
    # searches (official_asia.py), at most this many requests a day per language.
    official_asia: bool = True
    official_asia_daily_requests: int = 500

    def tcgdex_languages(self) -> set[str]:
        """TCGdex languages to read, all games'."""
        named = {_SETTING_ALIASES.get(lang, lang) for lang in self.languages}
        if self.asia_languages is None:
            asian = (named & ASIAN) or set(DEFAULT_ASIA_LANGUAGES)
        else:
            asian = {_SETTING_ALIASES.get(lang, lang) for lang in self.asia_languages}
        return (named - ASIAN) | (asian & ASIAN) | (named & {"zh-cn"})


INTERNATIONAL, ASIA, CHINA = "international", "asia", "china"


@dataclass(frozen=True)
class Region:
    """One of the Pokémon games: a publisher's market and its languages."""

    id: str
    name: str
    region: str
    region_label: str
    # TCGdex languages it reads (those `PokemonSettings` asks for) and open datasets.
    tcgdex: tuple[str, ...]
    datasets: tuple[str, ...]
    languages: tuple[str, ...]
    short_names: tuple[str, ...]


REGIONS = {
    INTERNATIONAL: Region(
        "pokemon",
        "Pokémon TCG",
        INTERNATIONAL,
        "International",
        ("en", "fr", "de", "it", "es", "pt"),
        (),
        ("en", "fr", "de", "it", "es", "pt"),
        ("pkm", "pokemon", "poke", "ptcg"),
    ),
    ASIA: Region(
        "pokemon-asia",
        "Pokémon TCG Asia",
        ASIA,
        "Asia",
        ("ja", "ko", "zh-tw", "th", "id"),
        ("ko",),
        ("ja", "ko", "zh-hant", "th", "id"),
        ("pkmasia", "pkmjp", "pokejp", "ptcgjp"),
    ),
    CHINA: Region(
        "pokemon-china",
        "Pokémon TCG China",
        CHINA,
        "China",
        ("zh-cn",),
        ("zh-hans",),
        ("zh-hans",),
        ("pkmcn", "pokecn", "ptcgcn"),
    ),
}
# Languages whose products are numbered their own way (Thai, Indonesian), and the prefix
# of their set ids when a Japanese set has their code.
SOUTHEAST_ASIAN = {"th", "id"}
SOUTHEAST_PREFIX = "sea:"
# Mainland Chinese set codes: "CSV9C", "CS5aC", "CS4.5C", "151C".
_CHINA_CODE = re.compile(r"^(?:CS[\w.+]*C|\d{2,3}C)$", re.IGNORECASE)


def region_of(hints: OcrHints) -> str:
    """The Pokémon game a scanned card belongs to, from its set code and writing."""
    if hints.set_code and _CHINA_CODE.match(hints.set_code):
        return CHINA
    if hints.lang in ("zh-hans", "zh-hant"):
        # Taiwan and Hong Kong cards print Japanese set codes, mainland ones "…C" codes.
        return ASIA if hints.set_code or hints.lang == "zh-hant" else CHINA
    if hints.lang in ("ja", "ko", "th"):
        return ASIA
    return INTERNATIONAL


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def card_key(lang: str, name: str) -> str:
    return f"{lang}:{name.casefold()}"


def tcgdex_set_id(external_id: str) -> str:
    """TCGdex id of a stored set."""
    return external_id.removeprefix(ASIAN_PREFIX)


def parse_set(raw: dict[str, Any], lang: str | None, external_id: str | None = None) -> SetData:
    abbreviation = (raw.get("abbreviation") or {}).get("official")
    released = raw.get("releaseDate")
    external_id = external_id or raw["id"]
    symbol = raw.get("symbol")
    # Symbols are listed under "univ/", which the asset server refuses; the English path
    # serves them. The symbol of a renamed Asian set is the international set's.
    if symbol and not external_id.startswith(ASIAN_PREFIX):
        icon_url = f"{symbol.replace('/univ/', '/en/')}.png"
    else:
        icon_url = None
    return SetData(
        external_id=external_id,
        code=abbreviation or raw["id"],
        name=raw["name"],
        lang=lang,
        release_date=date.fromisoformat(released) if released else None,
        total=(raw.get("cardCount") or {}).get("total"),
        icon_url=icon_url,
    )


def _digital(raw_set: dict[str, Any]) -> bool:
    return (raw_set.get("serie") or {}).get("id") in DIGITAL_SERIES


def _images(raw: dict[str, Any], lang: str) -> dict[str, str]:
    return {lang: f"{raw['image']}/high.webp"} if raw.get("image") else {}


def _finishes(raw: dict[str, Any]) -> list[str]:
    variants = raw.get("variants") or {}
    return [finish for key, finish in VARIANTS.items() if variants.get(key)] or ["normal"]


def _printed_name(raw: dict[str, Any], lang: str) -> str:
    """The card name, with Asian Pokémon names left in English or cut to a letter by
    TCGdex ("Smeargle", "a" for Unown A) written from their Pokédex number."""
    name = raw["name"]
    dex = raw.get("dexId") or []
    if lang not in ASIAN or raw.get("category") != "Pokemon" or len(dex) != 1 or not name.isascii():
        return name
    names = species_names().get(dex[0]) or {}
    local, english = names.get(LANGUAGES[lang]), names.get("en")
    if not local or not english:
        return name
    if english.casefold() in name.casefold():
        return re.sub(re.escape(english), local, name, count=1, flags=re.I)
    if len(name.strip()) <= 2:  # Unown letters and signs
        return f"{local}{name.strip().upper()}"
    return name


def parse_card(raw: dict[str, Any], set_id: str, lang: str) -> CardData:
    """A full card from a TCGdex card detail, in the language it was fetched in."""
    ours = LANGUAGES[lang]
    raw = {**raw, "name": _printed_name(raw, lang)}
    attributes = {
        k: raw[k]
        for k in ("category", "hp", "stage", "trainerType", "energyType", "evolveFrom", "dexId")
        if raw.get(k) is not None
    }
    printing_attributes = {
        k: raw[k]
        for k in ("regulationMark", "attacks", "abilities", "effect")
        if raw.get(k) is not None
    }
    market_ids = _market_ids(raw)
    if market_ids:
        printing_attributes["market_ids"] = market_ids
    printing = PrintingData(
        external_id=raw["localId"],
        set_external_id=set_id,
        collector_number=raw["localId"],
        rarity=raw.get("rarity"),
        artist=raw.get("illustrator"),
        finishes=_finishes(raw),
        languages=[ours],
        images=_images(raw, ours),
        attributes=printing_attributes,
    )
    pokemon = raw.get("category") == "Pokemon"
    names = card_translations(raw["name"], ours, raw.get("dexId") or [], pokemon) | {
        ours: raw["name"]
    }
    return CardData(
        external_id=card_key(lang, raw["name"]),
        name=raw["name"],
        colors=card_colors(raw.get("types") or [], raw.get("category")),
        attributes=attributes,
        printings=[printing],
        names=names,
    )


def _translation(key: str, raw: dict[str, Any], printing: PrintingRef, lang: str) -> CardData:
    """Name and image of a printing in another language, for the card `key`."""
    ours = LANGUAGES[lang]
    return CardData(
        external_id=key,
        name=raw["name"],
        printings=[
            PrintingData(
                external_id=printing.external_id,
                set_external_id=printing.set_external_id,
                collector_number=printing.external_id,
                languages=[ours],
                images=_images(raw, ours),
                names={ours: raw["name"]},
            )
        ],
        partial=True,
    )


def join_english(card: CardData, english_cards: set[str]) -> CardData:
    """Attach a card fetched in another language to the English card of the same name
    (known from species names): the printing stays full, card fields stay English."""
    english = card.names.get("en")
    key = card_key("en", english) if english else None
    if key is None or key == card.external_id or key not in english_cards:
        return card
    for printing in card.printings:
        printing.partial = False
        printing.names = {**printing.names, **{lang: card.name for lang in printing.languages}}
    card.external_id, card.partial = key, True
    return card


def translate_latin(card: CardData, latin: Mapping[str, Mapping[str, str]]) -> CardData:
    """Add the international names of the English card an Asian card is named after
    (`shared.International.latin_names`): a Korean Trainer then reads "보스의 지령 (Ordres
    du Boss)" to a French reader, not "(Boss's Orders)". Names already there stay."""
    english = card.names.get("en")
    found = latin.get(card_key("en", normalize_name(english))) if english else None
    if found:
        card.names = {**found, **card.names}
    return card


def join_asian_set(
    extra: asia.AsianSet,
    lang: str,
    fetched_sets: dict[tuple[bool, str], str],
    keys: dict[tuple[str, str], str],
    english_cards: set[str],
    set_langs: dict[str, str | None] | None = None,
) -> CatalogBatch:
    """Cards of a Korean or Chinese dataset set, or of an official Asian card search. A
    set of an Asian id already stored (from TCGdex) gets this language's names and images
    on its printings of the same number; other cards are added in full (joined to the
    English card when named after species). Cards without a name (listed, page not read)
    only join printings.

    `set_langs` (our set id -> its language): Thai and Indonesian products number their
    cards their own way, so they never join a set of another language that has their code
    (Japanese "SV-P" promos): they get a set of their own, shared by both."""
    asian_ids = {tcgdex.casefold(): ours for (asian, tcgdex), ours in fetched_sets.items() if asian}
    taken = {tcgdex.casefold() for asian, tcgdex in fetched_sets if not asian}
    code = extra.code
    set_id = asian_ids.get(code.casefold())
    if (
        set_langs is not None
        and lang in SOUTHEAST_ASIAN
        and set_id is not None
        and set_langs.get(set_id) not in SOUTHEAST_ASIAN
    ):
        code = f"{SOUTHEAST_PREFIX}{code}"
        set_id = asian_ids.get(code.casefold())
    batch = CatalogBatch()
    if set_id is None:
        set_id = f"{ASIAN_PREFIX}{code}" if code.casefold() in taken else code
        fetched_sets[(True, code)] = set_id
        if set_langs is not None:
            set_langs[set_id] = lang
        extra.data.external_id = set_id
        batch.sets.append(extra.data)
    numbers = {
        (asia.number_key(local)): (local, key)
        for (stored_set, local), key in keys.items()
        if stored_set == set_id
    }
    for card in extra.cards:
        printing = card.printings[0]
        printing.set_external_id = set_id
        known = numbers.get(asia.number_key(printing.external_id))
        if known is not None:
            local, key = known
            batch.cards.append(
                CardData(
                    external_id=key,
                    name=card.name,
                    printings=[
                        PrintingData(
                            external_id=local,
                            set_external_id=set_id,
                            collector_number=local,
                            languages=[lang],
                            images=printing.images,
                            names={lang: card.name} if card.name else {},
                        )
                    ],
                    # Its Latin names (English from the card names table) help the
                    # Japanese card when that one has none.
                    names={k: v for k, v in card.names.items() if k in LATIN_LANGUAGES},
                    partial=True,
                )
            )
            continue
        if not card.name:
            continue
        joined = join_english(card, english_cards)
        keys[(set_id, printing.external_id)] = joined.external_id
        batch.cards.append(joined)
    return batch


# TCGplayer price variants to finishes ("1stEditionHolofoil", "unlimitedHolofoil"...).
TCGPLAYER_VARIANTS = {
    "normal": "normal",
    "holofoil": "holo",
    "reverse-holofoil": "reverse",
    "1stEditionNormal": "first_edition",
    "1stEditionHolofoil": "first_edition",
    "unlimitedNormal": "normal",
    "unlimitedHolofoil": "holo",
}


def _market_ids(raw: dict[str, Any]) -> dict[str, int]:
    pricing = raw.get("pricing") or {}
    ids = {}
    if (pricing.get("cardmarket") or {}).get("idProduct"):
        ids["cardmarket"] = pricing["cardmarket"]["idProduct"]
    for variant in (pricing.get("tcgplayer") or {}).values():
        if isinstance(variant, dict) and variant.get("productId"):
            ids["tcgplayer"] = variant["productId"]
            break
    return ids


def _tcgplayer_prices(raw: dict[str, Any], set_id: str) -> list[PriceQuote]:
    tcgplayer = (raw.get("pricing") or {}).get("tcgplayer") or {}
    quotes: dict[str, PriceQuote] = {}
    for variant, finish in TCGPLAYER_VARIANTS.items():
        data = tcgplayer.get(variant)
        if not isinstance(data, dict) or finish in quotes:
            continue
        trend = _decimal(data.get("marketPrice")) or _decimal(data.get("midPrice"))
        if trend:
            quotes[finish] = PriceQuote(
                set_id,
                raw["localId"],
                finish,
                trend=trend,
                low=_decimal(data.get("lowPrice")),
                avg=_decimal(data.get("midPrice")),
                currency=tcgplayer.get("unit") or "USD",
                source="tcgplayer",
            )
    return list(quotes.values())


def cardmarket_suffixes(finishes: Iterable[str]) -> dict[str, str]:
    """Finish -> Cardmarket price field suffix. Cardmarket lists one product per card; its
    `-holo` prices are the reverse holo version, or the holo one when the card also
    exists without holo."""
    finishes = list(finishes)
    base = "normal" if "normal" in finishes else "holo" if "holo" in finishes else None
    if "reverse" in finishes:
        foil = "reverse"
    elif base == "normal" and "holo" in finishes:
        foil = "holo"
    else:
        foil = None
    return {finish: suffix for finish, suffix in ((base, ""), (foil, "-holo")) if finish}


def parse_prices(raw: dict[str, Any], set_id: str) -> list[PriceQuote]:
    """Cardmarket lists one product per card; its `-holo` prices are the reverse holo
    (or holo, when the card also exists without holo) version. TCGplayer lists a price
    per variant."""
    tcgplayer = _tcgplayer_prices(raw, set_id)
    cardmarket = (raw.get("pricing") or {}).get("cardmarket") or {}
    if not cardmarket:
        return tcgplayer
    quotes = []
    for finish, suffix in cardmarket_suffixes(_finishes(raw)).items():
        quote = PriceQuote(
            set_id,
            raw["localId"],
            finish,
            trend=_decimal(cardmarket.get(f"trend{suffix}")),
            low=_decimal(cardmarket.get(f"low{suffix}")),
            avg=_decimal(cardmarket.get(f"avg{suffix}")),
            currency=cardmarket.get("unit") or "EUR",
            source="cardmarket",
        )
        if quote.trend or quote.low or quote.avg:
            quotes.append(quote)
    return quotes + tcgplayer


PRINTED_LANGUAGES = {"EN": "en", "FR": "fr", "DE": "de", "IT": "it", "ES": "es", "PT": "pt"}
# "136/189", "TG05/TG30", "SV107/SV122", "001/073"
_NUMBER = re.compile(r"\b([A-Z]{0,4}\d{1,3}[a-z]?)\s*/\s*([A-Z]{0,4}\d{1,3})\b")
# Black star promos: "SWSH001", "SVP 045"
_PROMO = re.compile(r"\b(SWSH|SVP|SM|XY|BW)\s?(\d{2,3})\b")
# Since Scarlet & Violet: "G PAL EN 123/193"
_SET_LANG = re.compile(r"\b([A-Z][A-Z0-9]{1,4})\s+(" + "|".join(PRINTED_LANGUAGES) + r")\b")
# The regulation mark (one letter, D to M so far) read glued to the set code: "IMEG EN",
# or to the code and language both: "ICRIEN 048/122".
_GLUED_MARK = re.compile(r"^[D-M]([A-Z]{3})$")
_GLUED_SET_LANG = re.compile(
    r"\b[D-M]?([A-Z]{3})(" + "|".join(PRINTED_LANGUAGES) + r")\s*[0-9OIl]{1,3}\s*/"
)
# Digits misread as letters in the number ("O22/132", "1O0/132"); letter prefixes
# ("TG05/TG30") are left alone.
_MISREAD_NUMBER = re.compile(r"(?<![A-Za-z])([0-9OIl]{1,3})(\s*/\s*)([0-9OIl]{2,3})(?![A-Za-z])")
_DIGITS = str.maketrans("OIl", "011")
# Mega Evolution cards print "Mega" in its own style above the name: OCR may read it as a
# line of its own.
_MEGA = re.compile(r"^(mega|méga|m)$", re.IGNORECASE)


def _fix_number(text: str) -> str:
    def fix(match: re.Match) -> str:
        if not any(c.isdigit() for c in match.group(1) + match.group(3)):
            return match.group(0)
        number, slash, total = match.groups()
        return number.translate(_DIGITS) + slash + total.translate(_DIGITS)

    return _MISREAD_NUMBER.sub(fix, text)


# Asian cards print the set code right before the number: "SV1a 001/073".
# Mainland Chinese codes: "CSV9C", "CS5aC", "151C" (digits first), "CS4.5C".
# Never the weakness / resistance multiplier ("x2", "×2") of the line above the code.
_SET_CODE = (
    r"(?![xX]\d\b)(?=[\w.+]*[A-Za-z])"
    r"(?:[A-Za-z]{1,4}\d{1,2}(?:\.\d)?[a-zA-Z+]{0,2}|\d{2,3}[A-Za-z])"
)
_SET_BEFORE_NUMBER = re.compile(rf"\b({_SET_CODE})\s+[A-Z]{{0,4}}\d{{1,3}}\s*/")
# The code read glued to the number: "SV6a041/064" (Asian codes end with a small letter).
_SET_GLUED_NUMBER = re.compile(r"\b([A-Za-z]{1,4}\d{1,2}[a-z])(\d{3})\s*/\s*(\d{2,3})\b")
# Labels around the name: stage, HP, trainer kinds, in several languages.
# Asian labels are written without a space before the name: no word boundary there.
_STAGE = re.compile(
    r"^((basic|stage ?\d|base|niveau ?\d|basis|phase ?\d|fase ?\d|livello ?\d|básico)\b|"
    r"たね|\d進化|기본|\d진화|基础|基礎|\d阶进化|\d階進化|\d阶|\d階)[\s:.-]*",
    re.IGNORECASE,
)
_HP = re.compile(
    r"\s*((?<![A-Za-z])(HP|PV|KP|PS|PE)\s*\d{2,3}|\d{2,3}\s*(HP|PV|KP|PS|PE)\b)\s*",
    re.IGNORECASE,
)
# The set code box ("SV4K", "G SV1a") read as a line of its own.
_SET_ALONE = re.compile(rf"^(?:[A-Z]\s+)?({_SET_CODE})$")
_MARKERS = re.compile(
    r"Pokémon|Pokemon|Nintendo|GAME ?FREAK|Creatures|\b(HP|PV|KP)\s*\d|\d\s*(HP|PV|KP)\b|"
    r"ポケモン|포켓몬|宝可梦|寶可夢"
)
_SKIP = re.compile(
    r"^(trainer|dresseur|trainer-?karte|allenatore|entrenador|treinador|supporter|"
    r"supporters|item|objet|stadium|stade|energy|énergie|energie|tool|outil|"
    r"evolves from|évolue de|entwickelt sich aus|si evolve da|evoluciona de|evolui de|"
    r"pokémon|pokemon)\b|"
    # "进化自 …" / "從…進化" (evolves from) lines of Chinese cards.
    r"^(进化自|進化自|从.{1,8}进化|從.{1,8}進化)|"
    # Asian trainer and energy labels, alone on their line (card names such as
    # "エネルギーつけかえ" start with the same words).
    r"^(トレーナーズ|サポート|グッズ|スタジアム|ポケモンのどうぐ|基本エネルギー|特殊エネルギー|"
    r"エネルギー|트레이너스|서포트|아이템|스타디움|포켓몬의 도구|기본 에너지|특수 에너지|에너지|"
    r"訓練家|训练家|支援者|物品|竞技场|競技場|宝可梦道具|寶可夢道具|基本能量|特殊能量|能量)$",
    re.IGNORECASE,
)


# Words of the bottom rows (weakness, resistance, retreat) by language, for cards
# without a printed language code (before Scarlet & Violet).
_LANGUAGE_WORDS = {
    "fr": re.compile(r"\b(faiblesse|résistance|retraite)\b", re.IGNORECASE),
    "de": re.compile(r"\b(schwäche|resistenz|rückzug)\b", re.IGNORECASE),
    "it": re.compile(r"\b(debolezza|resistenza|ritirata)\b", re.IGNORECASE),
    "es": re.compile(r"\b(debilidad|resistencia|retirada)\b", re.IGNORECASE),
    "pt": re.compile(r"\b(fraqueza|resistência|recuo)\b", re.IGNORECASE),
    "en": re.compile(r"\b(weakness|resistance|retreat)\b", re.IGNORECASE),
}
# HP is written "PV" on French cards and "KP" on German ones.
_HP_LANGUAGE = re.compile(r"\b(PV|KP)\s*\d", re.IGNORECASE)


def _read_code(lines: list[OcrLine], hints: OcrHints) -> None:
    """Number and set code from the collector lines. A more telling form of the code
    ("TWM FR", "SV6a 041/") wins over a code alone on its line, whatever the order."""
    found: tuple[int, str, str | None] | None = None
    for line in lines:
        text = line.text
        number_text = _fix_number(text)
        if hints.collector_number is None and (match := _SET_GLUED_NUMBER.search(number_text)):
            hints.collector_number, hints.printed_total = match.group(2), match.group(3)
            if found is None or found[0] > 2:
                found = (2, match.group(1), None)
        elif hints.collector_number is None and (match := _NUMBER.search(number_text)):
            hints.collector_number, hints.printed_total = match.group(1), match.group(2)
        elif hints.collector_number is None and (match := _PROMO.search(text)):
            hints.collector_number = match.group(1) + match.group(2)
        if match := _SET_LANG.search(text):
            code = match.group(1)
            if glued := _GLUED_MARK.match(code):
                code = glued.group(1)
            candidate = (0, code, PRINTED_LANGUAGES[match.group(2)])
        elif match := _GLUED_SET_LANG.search(text):
            candidate = (1, match.group(1), PRINTED_LANGUAGES[match.group(2)])
        elif match := _SET_BEFORE_NUMBER.search(text):
            candidate = (2, match.group(1), None)
        elif match := _SET_ALONE.match(text.strip()):
            candidate = (3, match.group(1), None)
        else:
            continue
        if found is None or candidate[0] < found[0]:
            found = candidate
    if found:
        hints.set_code = found[1]
        hints.lang = found[2] or hints.lang
        if _CHINA_CODE.match(hints.set_code):
            # "151c": mainland codes end with a capital C.
            hints.set_code = hints.set_code[:-1] + "C"


def parse_ocr(lines: list[OcrLine]) -> OcrHints:
    ordered = by_position([OcrLine(clean(line.text), line.left, line.top) for line in lines])
    hints = OcrHints()
    bottom = bottom_part(ordered)
    _read_code(bottom, hints)
    if hints.collector_number is None:
        # Background text read around the card stretches the text box: the collector
        # line may sit above the bottom quarter. A "NNN/NNN" number is telling anywhere.
        for line in ordered:
            if match := _NUMBER.search(_fix_number(line.text)):
                hints.collector_number, hints.printed_total = match.group(1), match.group(2)
                break
    names = []
    for line in ordered:
        if line in bottom:
            continue
        text = _HP.sub(" ", _STAGE.sub("", line.text)).strip(" -:")
        if len(text) >= 2 and letter_ratio(text) > 0.5 and not _SKIP.match(text):
            names.append(text)
    if len(names) > 1 and _MEGA.match(names[0]):
        names = [f"{names[0]} {names[1]}", *names[2:]]
    if names:
        hints.name, hints.other_names = names[0], names[1:3]
    text = " ".join(line.text for line in ordered)
    hints.recognized = bool(_MARKERS.search(text))
    if hints.lang is None:
        hints.lang = script_language(lines)
    if hints.lang is None and (found := _HP_LANGUAGE.search(text)):
        hints.lang = {"PV": "fr", "KP": "de"}[found.group(1).upper()]
    if hints.lang is None:
        hints.lang = next(
            (lang for lang, words in _LANGUAGE_WORDS.items() if words.search(text)), None
        )
    return hints


class PokemonProvider:
    group = "pokemon"
    group_name = "Pokémon"
    colors = [
        ColorDef("grass", "Grass", "#78C850", ENERGY_SPRITE, (25, 50, 25, 25)),
        ColorDef("fire", "Fire", "#F08030", ENERGY_SPRITE, (0, 0, 25, 25)),
        ColorDef("water", "Water", "#6890F0", ENERGY_SPRITE, (75, 50, 25, 25)),
        ColorDef("lightning", "Lightning", "#F8D030", ENERGY_SPRITE, (50, 50, 25, 25)),
        ColorDef("psychic", "Psychic", "#F85888", ENERGY_SPRITE, (75, 25, 25, 25)),
        ColorDef("fighting", "Fighting", "#C03028", ENERGY_SPRITE, (50, 25, 25, 25)),
        ColorDef("darkness", "Darkness", "#705848", ENERGY_SPRITE, (0, 50, 25, 25)),
        ColorDef("metal", "Metal", "#B8B8D0", ENERGY_SPRITE, (75, 0, 25, 25)),
        ColorDef("fairy", "Fairy", "#EE99AC", ENERGY_SPRITE, (50, 0, 25, 25)),
        ColorDef("dragon", "Dragon", "#7038F8", ENERGY_SPRITE, (0, 25, 25, 25)),
        ColorDef("colorless", "Colorless", "#A8A878", ENERGY_SPRITE, (25, 0, 25, 25)),
        # Trainers and special Energies (drawn for Zukan, scripts/draw_color_symbols.py).
        ColorDef(NO_TYPE, "No type", "#D1D5DB", icon_file=SYMBOLS / "none.svg"),
    ]
    finishes = [
        FinishDef("normal", "Standard"),
        FinishDef("holo", "Holo"),
        FinishDef("reverse", "Reverse holo"),
        FinishDef("first_edition", "1st edition"),
    ]
    cardmarket_path = "Pokemon"
    # Cardmarket's price guide file (game 6) prices the printings TCGdex has a Cardmarket
    # product for but no prices (many Japanese cards): `app.prices.cardmarket`.
    cardmarket_guide = 6
    rarities = [
        RarityDef("common", "Common", ("C", "●")),
        RarityDef("uncommon", "Uncommon", ("U", "◆")),
        RarityDef("rare", "Rare", ("R", "★")),
        RarityDef(
            "holo_rare",
            "Holo Rare",
            (
                "Rare Holo",
                "Holo Rare V",
                "Holo Rare VMAX",
                "Holo Rare VSTAR",
                "Rare Holo LV.X",
                "Rare PRIME",
                "LEGEND",
                "Rare Holo EX",
                "Rare Holo GX",
                "Rare Holo V",
            ),
        ),
        RarityDef("double_rare", "Double Rare", ("RR",)),
        RarityDef("triple_rare", "Triple Rare", ("RRR",)),
        RarityDef("ace_spec", "ACE SPEC Rare", ("ACE",)),
        RarityDef("radiant", "Radiant Rare", ("K",)),
        RarityDef("amazing", "Amazing Rare", ("A",)),
        RarityDef("illustration_rare", "Illustration Rare", ("AR",)),
        RarityDef("character_rare", "Character Rare", ("CHR", "Character Holo Rare")),
        RarityDef("ultra_rare", "Ultra Rare", ("UR", "Full Art Trainer", "Rare Ultra")),
        RarityDef("character_super_rare", "Character Super Rare", ("CSR",)),
        RarityDef("special_illustration_rare", "Special Illustration Rare", ("SAR",)),
        RarityDef(
            "shiny_rare", "Shiny Rare", ("S", "Shiny rare V", "Shiny rare VMAX", "Rare Shiny")
        ),
        RarityDef("shiny_ultra_rare", "Shiny Ultra Rare", ("SSR",)),
        RarityDef("secret_rare", "Secret Rare", ("SR", "Rare Secret", "Rare Rainbow")),
        RarityDef("hyper_rare", "Hyper Rare", ("HR", "Mega Hyper Rare")),
        RarityDef("promo", "Promo", ("PR",)),
    ]
    filters = [
        FilterDef("category", "Category", "category"),
        FilterDef("trainer_type", "Trainer type", "trainerType"),
        FilterDef("stage", "Stage", "stage"),
        FilterDef("rarity", "Rarity"),
    ]
    legal_notice = LEGAL_NOTICE
    # 2: one set per set id across Asian languages, names from species names.
    # 3: Asian sets reusing an international id stored apart, Asian names fixed.
    # 4: Thai and Indonesian, Korean and Simplified Chinese from open datasets.
    # 5: "No type" for Trainers and special Energies.
    # 6: Pokémon TCG API dropped, English pictures it gave refilled from the other sources.
    # 7: one game per market (international, Asia, China).
    # 8: Thai, Indonesian, Traditional Chinese and Korean cards of the official searches.
    # 9: Asian Trainers, Energies and Pokémon named with other words translated (card
    #    names table), international names of the English card.
    catalog_version = 9

    def __init__(self, region: str = INTERNATIONAL):
        self.market = REGIONS[region]
        self.id = self.market.id
        self.name = self.market.name
        self.region = self.market.region
        self.region_label = self.market.region_label
        self.languages = list(self.market.languages)
        self.short_names = list(self.market.short_names)
        # Mainland Chinese data has no prices.
        self.price_sources = [] if region == CHINA else ["cardmarket", "tcgplayer"]
        self.secondary_sources = [official_jp.source] if region == ASIA else []
        # Collection copies without a picture in their language: Japanese for Asia, none
        # for China (its cards are printed nowhere else).
        self.image_fallback = {ASIA: "ja", CHINA: None}.get(region, "en")
        if region == CHINA:
            self.cardmarket_guide = None

    async def _get(self, http: httpx.AsyncClient, path: str) -> Any:
        return (await get_with_retry(http, f"{API_URL}{path}")).json()

    async def _cards(
        self, http: httpx.AsyncClient, lang: str, ids: Iterable[str]
    ) -> list[dict[str, Any]]:
        """Card details, fetched concurrently. Missing cards are logged and skipped."""
        semaphore = asyncio.Semaphore(CONCURRENCY)

        async def one(card_id: str) -> dict[str, Any] | None:
            async with semaphore:
                try:
                    # Ids are literal ("exu-%3F", "SM1+"), so escape every character.
                    return await self._get(http, f"/{lang}/cards/{quote(card_id, safe='')}")
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 404:
                        raise
                    log.warning("TCGdex card %s/%s not found", lang, card_id)
                    return None

        results = await asyncio.gather(*(one(card_id) for card_id in ids))
        return [r for r in results if r is not None]

    async def _full_set(
        self,
        http: httpx.AsyncClient,
        lang: str,
        raw_set: dict[str, Any],
        set_lang: str | None,
        external_id: str,
    ) -> CatalogBatch:
        card_set = parse_set(raw_set, set_lang, external_id)
        batch = CatalogBatch(sets=[card_set])
        details = await self._cards(http, lang, (c["id"] for c in raw_set.get("cards", [])))
        for raw in details:
            batch.cards.append(parse_card(raw, card_set.external_id, lang))
            batch.prices += parse_prices(raw, card_set.external_id)
        return batch

    async def fetch_catalog(self, http: httpx.AsyncClient) -> AsyncIterator[CatalogBatch]:
        settings = PokemonSettings()
        wanted = settings.tcgdex_languages() & set(self.market.tcgdex)
        languages = [lang for lang in BASE_ORDER if lang in wanted]
        # Card key of each printing of the sets fetched in full, to attach translations.
        keys: dict[tuple[str, str], str] = {}
        # Our set id of each TCGdex set id, per language family (international, Asian).
        fetched_sets: dict[tuple[bool, str], str] = {}
        # Language of each Asian set fetched in full (official searches join by it).
        set_langs: dict[str, str | None] = {}
        english_cards: set[str] = set()
        latin: Mapping[str, Mapping[str, str]] = {}
        if self.region != INTERNATIONAL:
            # Ids the international game uses and its card names (`shared.py`).
            known = await shared.international(http, API_URL, DIGITAL_SERIES)
            fetched_sets = {(False, set_id): set_id for set_id in known.set_ids}
            english_cards = set(known.english_cards)
            latin = known.latin_names

        def translated(batch: CatalogBatch) -> CatalogBatch:
            for card in batch.cards:
                translate_latin(card, latin)
            return batch

        for lang in languages:
            asian = lang in ASIAN
            for brief in await self._get(http, f"/{lang}/sets"):
                raw_set = await self._get(http, f"/{lang}/sets/{quote(brief['id'], safe='')}")
                if _digital(raw_set):
                    continue
                if (asian, brief["id"]) in fetched_sets:
                    set_id = fetched_sets[(asian, brief["id"])]
                    yield translated(
                        await self._translations(http, lang, raw_set, set_id, keys, english_cards)
                    )
                    continue
                taken = asian and (False, brief["id"]) in fetched_sets
                set_id = f"{ASIAN_PREFIX}{brief['id']}" if taken else brief["id"]
                fetched_sets[(asian, brief["id"])] = set_id
                # International sets have no language: they are printed in many.
                batch = await self._full_set(
                    http, lang, raw_set, None if lang == "en" else LANGUAGES[lang], set_id
                )
                set_langs[set_id] = None if lang == "en" else LANGUAGES[lang]
                if lang == "en":
                    english_cards |= {card.external_id for card in batch.cards}
                else:
                    batch.cards = [join_english(card, english_cards) for card in batch.cards]
                for card in batch.cards:
                    for printing in card.printings:
                        keys[(printing.set_external_id, printing.external_id)] = card.external_id
                yield translated(batch)
        extra = []
        if settings.korean and "ko" in self.market.datasets:
            extra.append(("ko", asia.korean_sets))
        if settings.chinese and "zh-hans" in self.market.datasets:
            extra.append(("zh-hans", asia.chinese_sets))
        for lang, read in extra:
            try:
                sets = await read(http)
            except httpx.HTTPError:
                # TCGdex's data is stored already: a missing dataset does not undo it.
                log.exception("Pokémon %s dataset could not be read", lang)
                continue
            for extra_set in sets:
                yield translated(join_asian_set(extra_set, lang, fetched_sets, keys, english_cards))
                if ours := fetched_sets.get((True, extra_set.code)):
                    set_langs.setdefault(ours, lang)
        official = [lang for lang in official_asia.LANGUAGES if lang in self.languages]
        if settings.official_asia and self.region == ASIA and official:
            found = await official_asia.read_sites(
                http, official, settings.official_asia_daily_requests
            )
            # Japanese codes first (Traditional Chinese, Korean). Indonesian before Thai:
            # its English names join the English cards, Thai names then join its printings.
            for lang in ("zh-hant", "ko", "id", "th"):
                for extra_set in found.get(lang, []):
                    yield translated(
                        join_asian_set(
                            extra_set, lang, fetched_sets, keys, english_cards, set_langs
                        )
                    )

    async def _translations(
        self,
        http: httpx.AsyncClient,
        lang: str,
        raw_set: dict[str, Any],
        set_id: str,
        keys: dict[tuple[str, str], str],
        english_cards: set[str],
    ) -> CatalogBatch:
        ours = LANGUAGES[lang]
        batch = CatalogBatch()
        missing = []
        for brief in raw_set.get("cards", []):
            key = keys.get((set_id, brief["localId"]))
            if key is None:
                missing.append(brief["id"])
                continue
            batch.cards.append(
                CardData(
                    external_id=key,
                    name=brief["name"],
                    printings=[
                        PrintingData(
                            external_id=brief["localId"],
                            set_external_id=set_id,
                            collector_number=brief["localId"],
                            languages=[ours],
                            images=_images(brief, ours),
                            names={ours: brief["name"]},
                        )
                    ],
                    partial=True,
                )
            )
        # Printings only listed in this language: fetch them in full.
        for raw in await self._cards(http, lang, missing):
            card = join_english(parse_card(raw, set_id, lang), english_cards)
            batch.cards.append(card)
            batch.prices += parse_prices(raw, set_id)
        return batch

    async def fetch_cards(
        self, http: httpx.AsyncClient, cards: list[CardRef]
    ) -> AsyncIterator[CatalogBatch]:
        """Each printing again in its base language, plus the languages it has no image
        in yet (names and images only)."""
        reverse = {ours: theirs for theirs, ours in LANGUAGES.items()}
        for ref in cards:
            batch = CatalogBatch()
            for printing in ref.printings:
                card_id = f"{tcgdex_set_id(printing.set_external_id)}-{printing.external_id}"
                base = reverse.get(printing.set_lang or "en", "en")
                for raw in await self._cards(http, base, [card_id]):
                    card = parse_card(raw, printing.set_external_id, base)
                    if card.external_id != ref.external_id:
                        # Joined to another card (English one): keep it there.
                        for p in card.printings:
                            p.partial = False
                        card.external_id, card.partial = ref.external_id, True
                    batch.cards.append(card)
                    batch.prices += parse_prices(raw, printing.set_external_id)
                missing = [
                    reverse[lang]
                    for lang in printing.languages
                    if lang in reverse
                    and lang not in printing.image_languages
                    and reverse[lang] != base
                ]
                for lang in missing:
                    for raw in await self._cards(http, lang, [card_id]):
                        batch.cards.append(_translation(ref.external_id, raw, printing, lang))
            if batch.cards:
                yield batch

    async def lookup(self, http: httpx.AsyncClient, hints: OcrHints) -> CatalogBatch | None:
        """A scanned card missing from the catalog, by set id and number (English listing
        first: international sets are stored from it; Japanese first in Asia)."""
        if not (hints.set_code and hints.collector_number):
            return None
        reverse = {ours: theirs for theirs, ours in LANGUAGES.items()}
        number = hints.collector_number.lstrip("0") or "0"
        # TCGdex ids differ from printed codes since Scarlet & Violet ("MEG" is me01).
        set_id = tcgdex_set_id(hints.set_external_id) if hints.set_external_id else hints.set_code
        base = "en" if self.region == INTERNATIONAL else "ja"
        tried = [base, reverse.get(hints.lang or "", base)]
        languages = [lang for lang in dict.fromkeys(tried) if lang in self.market.tcgdex]
        international = False  # the id is an international set's
        if self.region != INTERNATIONAL and languages:
            known = await shared.international(http, API_URL, DIGITAL_SERIES)
            international = set_id in known.set_ids
        for lang in languages:
            try:
                raw_set = await self._get(http, f"/{lang}/sets/{quote(set_id, safe='')}")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
                continue
            if _digital(raw_set):
                return None
            international = international or lang not in ASIAN
            brief = next(
                (
                    c
                    for c in raw_set.get("cards", [])
                    if (c["localId"].lstrip("0") or "0").casefold() == number.casefold()
                ),
                None,
            )
            if brief is None:
                continue
            renamed = lang in ASIAN and international
            card_set = parse_set(
                raw_set,
                None if lang == "en" else LANGUAGES[lang],
                f"{ASIAN_PREFIX}{raw_set['id']}" if renamed else None,
            )
            batch = CatalogBatch(sets=[card_set])
            for raw in await self._cards(http, lang, [brief["id"]]):
                batch.cards.append(parse_card(raw, card_set.external_id, lang))
                batch.prices += parse_prices(raw, card_set.external_id)
            return batch
        return None

    async def fetch_prices(
        self, http: httpx.AsyncClient, owned: list[PriceTarget]
    ) -> AsyncIterator[list[PriceQuote]]:
        # No bulk price data: refresh the cards people own (the catalog sync prices the
        # rest weekly).
        by_lang: dict[str, list[PriceTarget]] = {}
        reverse = {ours: theirs for theirs, ours in LANGUAGES.items()}
        for target in owned:
            by_lang.setdefault(reverse.get(target.set_lang or "en", "en"), []).append(target)
        for lang, targets in by_lang.items():
            for start in range(0, len(targets), 200):
                chunk = targets[start : start + 200]
                # TCGdex card id -> our set id.
                sets = {
                    f"{tcgdex_set_id(t.set_external_id)}-{t.printing_external_id}": (
                        t.set_external_id
                    )
                    for t in chunk
                }
                quotes: list[PriceQuote] = []
                for raw in await self._cards(http, lang, sets):
                    quotes += parse_prices(raw, sets.get(raw["id"], raw["set"]["id"]))
                yield quotes

    def cardmarket_suffixes(self, finishes: Iterable[str]) -> dict[str, str]:
        return cardmarket_suffixes(finishes)

    def image_file_stems(self, printing: Printing) -> list[str]:
        return []

    def parse_ocr(self, lines: list[OcrLine]) -> OcrHints:
        hints = parse_ocr(lines)
        # A Pokémon card of another market is that game's.
        hints.recognized = hints.recognized and region_of(hints) == self.region
        return hints
