"""Pokémon TCG, data from TCGdex (https://tcgdex.dev).

TCGdex has no bulk export, so card details are fetched one by one:
- English sets: every card in full (types, rarity, variants, Cardmarket prices).
- Other languages: a set id listed in several languages is one set (international
  sets share English ids, Asian sets share ids between Japanese, Korean and Chinese).
  A few Japanese sets reuse an international id for other cards (Japanese "neo2" is not
  Neo Discovery): they are stored as `asia:<id>`.
  Its base language (English, else Japanese, Korean, Traditional then Simplified
  Chinese) is fetched in full; the other listings only add printed names and images
  (partial data).

Pokémon has no card id shared across printings; printings are grouped by name. Names
made of species names (`species.py`) are known in every language, so Asian printings
of "ルギアV" join the English "Lugia V" card. Other cards stay grouped per language.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Iterable
from datetime import date
from decimal import Decimal
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
    SetData,
)
from app.games.ocr import bottom_part, by_position, clean, letter_ratio, script_language
from app.games.pokemon import pokemontcg
from app.games.pokemon.species import derive_names, species_names
from app.models import Printing

log = logging.getLogger(__name__)

API_URL = "https://api.tcgdex.net/v2"
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
}
# Base language order for sets listed in several languages (zh-cn data partly comes in
# Traditional characters, so it comes last).
BASE_ORDER = ["en", "fr", "de", "it", "es", "pt", "ja", "ko", "zh-tw", "zh-cn"]
ASIAN = {"ja", "ko", "zh-tw", "zh-cn"}
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

    # TCGdex languages to import. Asian languages add ~40k cards fetched one by one.
    languages: list[str] = list(LANGUAGES)


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
    names = {ours: raw["name"]}
    if raw.get("category") == "Pokemon":
        names = derive_names(raw["name"], ours, raw.get("dexId") or []) | names
    return CardData(
        external_id=card_key(lang, raw["name"]),
        name=raw["name"],
        colors=[t.lower() for t in raw.get("types") or []],
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


def parse_prices(raw: dict[str, Any], set_id: str) -> list[PriceQuote]:
    """Cardmarket lists one product per card; its `-holo` prices are the reverse holo
    (or holo, when the card also exists without holo) version. TCGplayer lists a price
    per variant."""
    tcgplayer = _tcgplayer_prices(raw, set_id)
    cardmarket = (raw.get("pricing") or {}).get("cardmarket") or {}
    if not cardmarket:
        return tcgplayer
    finishes = _finishes(raw)
    base = "normal" if "normal" in finishes else "holo" if "holo" in finishes else None
    if "reverse" in finishes:
        foil = "reverse"
    elif base == "normal" and "holo" in finishes:
        foil = "holo"
    else:
        foil = None
    quotes = []
    for finish, suffix in ((base, ""), (foil, "-holo")):
        if finish is None:
            continue
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
_NUMBER = re.compile(r"\b([A-Z]{0,4}\d{1,3}[a-z]?)\s*/\s*[A-Z]{0,4}\d{1,3}\b")
# Black star promos: "SWSH001", "SVP 045"
_PROMO = re.compile(r"\b(SWSH|SVP|SM|XY|BW)\s?(\d{2,3})\b")
# Since Scarlet & Violet: "G PAL EN 123/193"
_SET_LANG = re.compile(r"\b([A-Z][A-Z0-9]{1,4})\s+(" + "|".join(PRINTED_LANGUAGES) + r")\b")
# Asian cards print the set code right before the number: "SV1a 001/073".
_SET_BEFORE_NUMBER = re.compile(r"\b([A-Za-z]{1,4}\d{1,2}[a-zA-Z+]?)\s+[A-Z]{0,4}\d{1,3}\s*/")
# Labels around the name: stage, HP, trainer kinds, in several languages.
# Asian labels are written without a space before the name: no word boundary there.
_STAGE = re.compile(
    r"^((basic|stage ?\d|base|niveau ?\d|basis|phase ?\d|fase ?\d|livello ?\d|básico)\b|"
    r"たね|\d進化|기본|\d진화|基础|基礎|\d阶|\d階)[\s:.-]*",
    re.IGNORECASE,
)
_HP = re.compile(
    r"\s*((?<![A-Za-z])(HP|PV|KP|PS|PE)\s*\d{2,3}|\d{2,3}\s*(HP|PV|KP|PS|PE)\b)\s*",
    re.IGNORECASE,
)
# The set code box ("SV4K", "G SV1a") read as a line of its own.
_SET_ALONE = re.compile(r"^(?:[A-Z]\s+)?([A-Za-z]{1,4}\d{1,2}[a-zA-Z+]?)$")
_MARKERS = re.compile(
    r"Pokémon|Pokemon|Nintendo|GAME ?FREAK|Creatures|\b(HP|PV|KP)\s*\d|\d\s*(HP|PV|KP)\b|"
    r"ポケモン|포켓몬|宝可梦|寶可夢"
)
_SKIP = re.compile(
    r"^(trainer|dresseur|trainer-?karte|allenatore|entrenador|treinador|supporter|"
    r"supporters|item|objet|stadium|stade|energy|énergie|energie|tool|outil|"
    r"evolves from|évolue de|entwickelt sich aus|si evolve da|evoluciona de|evolui de|"
    r"pokémon|pokemon)\b|"
    # Asian trainer and energy labels, alone on their line (card names such as
    # "エネルギーつけかえ" start with the same words).
    r"^(トレーナーズ|サポート|グッズ|スタジアム|ポケモンのどうぐ|基本エネルギー|特殊エネルギー|"
    r"エネルギー|트레이너스|서포트|아이템|스타디움|포켓몬의 도구|기본 에너지|특수 에너지|에너지|"
    r"訓練家|训练家|支援者|物品|竞技场|競技場|宝可梦道具|寶可夢道具|基本能量|特殊能量|能量)$",
    re.IGNORECASE,
)


def parse_ocr(lines: list[OcrLine]) -> OcrHints:
    ordered = by_position([OcrLine(clean(line.text), line.left, line.top) for line in lines])
    hints = OcrHints()
    bottom = bottom_part(ordered)
    for line in bottom:
        if hints.collector_number is None and (match := _NUMBER.search(line.text)):
            hints.collector_number = match.group(1)
        elif hints.collector_number is None and (match := _PROMO.search(line.text)):
            hints.collector_number = match.group(1) + match.group(2)
        if hints.set_code is None and (match := _SET_LANG.search(line.text)):
            hints.set_code, hints.lang = match.group(1), PRINTED_LANGUAGES[match.group(2)]
        elif hints.set_code is None and (match := _SET_BEFORE_NUMBER.search(line.text)):
            hints.set_code = match.group(1)
        elif hints.set_code is None and (match := _SET_ALONE.match(line.text.strip())):
            hints.set_code = match.group(1)
    names = []
    for line in ordered:
        if line in bottom:
            continue
        text = _HP.sub(" ", _STAGE.sub("", line.text)).strip(" -:")
        if len(text) >= 2 and letter_ratio(text) > 0.5 and not _SKIP.match(text):
            names.append(text)
    if names:
        hints.name, hints.other_names = names[0], names[1:3]
    text = " ".join(line.text for line in ordered)
    hints.recognized = bool(_MARKERS.search(text))
    if hints.lang is None:
        # HP is written "PV" on French cards and "KP" on German ones.
        found = re.search(r"\b(PV|KP)\s*\d", " ".join(line.text for line in lines))
        hp_language = {"PV": "fr", "KP": "de"}
        hints.lang = script_language(lines) or (hp_language[found.group(1)] if found else None)
    return hints


class PokemonProvider:
    id = "pokemon"
    name = "Pokémon TCG"
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
    ]
    finishes = [
        FinishDef("normal", "Standard"),
        FinishDef("holo", "Holo"),
        FinishDef("reverse", "Reverse holo"),
        FinishDef("first_edition", "1st edition"),
    ]
    languages = list(LANGUAGES.values())
    price_sources = ["cardmarket", "tcgplayer"]
    cardmarket_path = "Pokemon"
    secondary_sources = [pokemontcg.source]
    filters = [
        FilterDef("category", "Category", "category"),
        FilterDef("trainer_type", "Trainer type", "trainerType"),
        FilterDef("stage", "Stage", "stage"),
        FilterDef("rarity", "Rarity"),
    ]
    short_names = ["pkm", "pokemon", "poke", "ptcg"]
    # 2: one set per set id across Asian languages, names from species names.
    # 3: Asian sets reusing an international id stored apart, Asian names fixed.
    catalog_version = 3

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
        wanted = set(PokemonSettings().languages)
        languages = [lang for lang in BASE_ORDER if lang in wanted]
        # Card key of each printing of the sets fetched in full, to attach translations.
        keys: dict[tuple[str, str], str] = {}
        # Our set id of each TCGdex set id, per language family (international, Asian).
        fetched_sets: dict[tuple[bool, str], str] = {}
        english_cards: set[str] = set()
        for lang in languages:
            asian = lang in ASIAN
            for brief in await self._get(http, f"/{lang}/sets"):
                raw_set = await self._get(http, f"/{lang}/sets/{quote(brief['id'], safe='')}")
                if _digital(raw_set):
                    continue
                if (asian, brief["id"]) in fetched_sets:
                    set_id = fetched_sets[(asian, brief["id"])]
                    yield await self._translations(http, lang, raw_set, set_id, keys, english_cards)
                    continue
                taken = asian and (False, brief["id"]) in fetched_sets
                set_id = f"{ASIAN_PREFIX}{brief['id']}" if taken else brief["id"]
                fetched_sets[(asian, brief["id"])] = set_id
                # International sets have no language: they are printed in many.
                batch = await self._full_set(
                    http, lang, raw_set, None if lang == "en" else LANGUAGES[lang], set_id
                )
                if lang == "en":
                    english_cards |= {card.external_id for card in batch.cards}
                else:
                    batch.cards = [join_english(card, english_cards) for card in batch.cards]
                for card in batch.cards:
                    for printing in card.printings:
                        keys[(printing.set_external_id, printing.external_id)] = card.external_id
                yield batch

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
        first: international sets are stored from it)."""
        if not (hints.set_code and hints.collector_number):
            return None
        reverse = {ours: theirs for theirs, ours in LANGUAGES.items()}
        number = hints.collector_number.lstrip("0") or "0"
        international = False  # the id is an international set's
        for lang in dict.fromkeys(["en", reverse.get(hints.lang or "", "en")]):
            try:
                raw_set = await self._get(http, f"/{lang}/sets/{quote(hints.set_code, safe='')}")
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

    def image_file_stems(self, printing: Printing) -> list[str]:
        return []

    def parse_ocr(self, lines: list[OcrLine]) -> OcrHints:
        return parse_ocr(lines)
