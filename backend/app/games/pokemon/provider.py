"""Pokémon TCG, data from TCGdex (https://tcgdex.dev).

TCGdex has no bulk export, so card details are fetched one by one:
- English sets: every card in full (types, rarity, variants, Cardmarket prices).
- Other languages: international sets share English set ids, so the translated set
  listing only adds printed names (partial data). Sets that exist only in one language
  (most Japanese, Korean and Chinese sets) are fetched in full and stay separate sets.

Pokémon has no card id shared across printings; printings are grouped by name, per
language for language-exclusive sets.
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
    CatalogBatch,
    ColorDef,
    FinishDef,
    OcrHints,
    OcrLine,
    PriceQuote,
    PriceTarget,
    PrintingData,
    SetData,
)
from app.games.ocr import bottom_part, by_position, clean, letter_ratio, script_language
from app.models import Printing

log = logging.getLogger(__name__)

API_URL = "https://api.tcgdex.net/v2"
CONCURRENCY = 8
# Series that are not physical cards (Pokémon TCG Pocket is a mobile game).
DIGITAL_SERIES = {"tcgp"}

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


def parse_set(raw: dict[str, Any], lang: str | None) -> SetData:
    abbreviation = (raw.get("abbreviation") or {}).get("official")
    released = raw.get("releaseDate")
    return SetData(
        external_id=raw["id"],
        code=abbreviation or raw["id"],
        name=raw["name"],
        lang=lang,
        release_date=date.fromisoformat(released) if released else None,
        total=(raw.get("cardCount") or {}).get("total"),
        icon_url=f"{raw['symbol']}.png" if raw.get("symbol") else None,
    )


def _digital(raw_set: dict[str, Any]) -> bool:
    return (raw_set.get("serie") or {}).get("id") in DIGITAL_SERIES


def _image(raw: dict[str, Any]) -> str | None:
    return f"{raw['image']}/high.webp" if raw.get("image") else None


def _finishes(raw: dict[str, Any]) -> list[str]:
    variants = raw.get("variants") or {}
    return [finish for key, finish in VARIANTS.items() if variants.get(key)] or ["normal"]


def parse_card(raw: dict[str, Any], set_id: str, lang: str) -> CardData:
    """A full card from a TCGdex card detail, in the language it was fetched in."""
    ours = LANGUAGES[lang]
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
    cardmarket = (raw.get("pricing") or {}).get("cardmarket") or {}
    if cardmarket.get("idProduct"):
        printing_attributes["cardmarket_id"] = cardmarket["idProduct"]
    printing = PrintingData(
        external_id=raw["localId"],
        set_external_id=set_id,
        collector_number=raw["localId"],
        rarity=raw.get("rarity"),
        artist=raw.get("illustrator"),
        finishes=_finishes(raw),
        languages=[ours],
        image_url=_image(raw),
        attributes=printing_attributes,
    )
    return CardData(
        external_id=card_key(lang, raw["name"]),
        name=raw["name"],
        colors=[t.lower() for t in raw.get("types") or []],
        attributes=attributes,
        printings=[printing],
        names={ours: raw["name"]},
    )


def parse_prices(raw: dict[str, Any], set_id: str) -> list[PriceQuote]:
    """Cardmarket lists one product per card; its `-holo` prices are the reverse holo
    (or holo, when the card also exists without holo) version."""
    cardmarket = (raw.get("pricing") or {}).get("cardmarket") or {}
    if not cardmarket:
        return []
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
        )
        if quote.trend or quote.low or quote.avg:
            quotes.append(quote)
    return quotes


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
_STAGE = re.compile(
    r"^(basic|stage ?\d|base|niveau ?\d|basis|phase ?\d|fase ?\d|livello ?\d|básico|"
    r"たね|\d進化|기본|\d진화|基础|基礎|\d阶|\d階)\b[\s:.-]*",
    re.IGNORECASE,
)
_HP = re.compile(
    r"\s*(\b(HP|PV|KP|PS|PE)\s*\d{2,3}|\d{2,3}\s*(HP|PV|KP|PS|PE)\b)\s*", re.IGNORECASE
)
_MARKERS = re.compile(
    r"Pokémon|Pokemon|Nintendo|GAME ?FREAK|Creatures|\b(HP|PV|KP)\s*\d|\d\s*(HP|PV|KP)\b|"
    r"ポケモン|포켓몬|宝可梦|寶可夢"
)
_SKIP = re.compile(
    r"^(trainer|dresseur|trainer-?karte|allenatore|entrenador|treinador|supporter|"
    r"supporters|item|objet|stadium|stade|energy|énergie|energie|tool|outil|"
    r"evolves from|évolue de|entwickelt sich aus|si evolve da|evoluciona de|evolui de|"
    r"pokémon|pokemon)\b",
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
        ColorDef("grass", "Grass", "#78C850"),
        ColorDef("fire", "Fire", "#F08030"),
        ColorDef("water", "Water", "#6890F0"),
        ColorDef("lightning", "Lightning", "#F8D030"),
        ColorDef("psychic", "Psychic", "#F85888"),
        ColorDef("fighting", "Fighting", "#C03028"),
        ColorDef("darkness", "Darkness", "#705848"),
        ColorDef("metal", "Metal", "#B8B8D0"),
        ColorDef("fairy", "Fairy", "#EE99AC"),
        ColorDef("dragon", "Dragon", "#7038F8"),
        ColorDef("colorless", "Colorless", "#A8A878"),
    ]
    finishes = [
        FinishDef("normal", "Normal"),
        FinishDef("holo", "Holo"),
        FinishDef("reverse", "Reverse holo"),
        FinishDef("first_edition", "1st edition"),
    ]
    languages = list(LANGUAGES.values())
    price_source = "tcgdex-cardmarket"

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
        self, http: httpx.AsyncClient, lang: str, raw_set: dict[str, Any], set_lang: str | None
    ) -> CatalogBatch:
        card_set = parse_set(raw_set, set_lang)
        batch = CatalogBatch(sets=[card_set])
        details = await self._cards(http, lang, (c["id"] for c in raw_set.get("cards", [])))
        for raw in details:
            batch.cards.append(parse_card(raw, card_set.external_id, lang))
            batch.prices += parse_prices(raw, card_set.external_id)
        return batch

    async def fetch_catalog(self, http: httpx.AsyncClient) -> AsyncIterator[CatalogBatch]:
        languages = [lang for lang in PokemonSettings().languages if lang in LANGUAGES]
        # English card key of each international printing, to attach translations.
        english: dict[tuple[str, str], str] = {}
        english_sets: set[str] = set()

        if "en" in languages:
            for brief in await self._get(http, "/en/sets"):
                raw_set = await self._get(http, f"/en/sets/{quote(brief['id'], safe='')}")
                if _digital(raw_set):
                    continue
                batch = await self._full_set(http, "en", raw_set, None)
                english_sets.add(brief["id"])
                for card in batch.cards:
                    for printing in card.printings:
                        english[(printing.set_external_id, printing.external_id)] = card.external_id
                yield batch

        for lang in languages:
            if lang == "en":
                continue
            for brief in await self._get(http, f"/{lang}/sets"):
                raw_set = await self._get(http, f"/{lang}/sets/{quote(brief['id'], safe='')}")
                if _digital(raw_set):
                    continue
                if brief["id"] not in english_sets:
                    yield await self._full_set(http, lang, raw_set, LANGUAGES[lang])
                    continue
                yield await self._translations(http, lang, raw_set, english)

    async def _translations(
        self,
        http: httpx.AsyncClient,
        lang: str,
        raw_set: dict[str, Any],
        english: dict[tuple[str, str], str],
    ) -> CatalogBatch:
        set_id = raw_set["id"]
        ours = LANGUAGES[lang]
        batch = CatalogBatch()
        missing = []
        for brief in raw_set.get("cards", []):
            key = english.get((set_id, brief["localId"]))
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
                            names={ours: brief["name"]},
                        )
                    ],
                    partial=True,
                )
            )
        # Printings only listed in this language: fetch them in full.
        for raw in await self._cards(http, lang, missing):
            card = parse_card(raw, set_id, lang)
            batch.cards.append(card)
            batch.prices += parse_prices(raw, set_id)
        return batch

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
                ids = [f"{t.set_external_id}-{t.printing_external_id}" for t in chunk]
                quotes: list[PriceQuote] = []
                for raw in await self._cards(http, lang, ids):
                    quotes += parse_prices(raw, raw["set"]["id"])
                yield quotes

    def image_file_stems(self, printing: Printing) -> list[str]:
        return []

    def parse_ocr(self, lines: list[OcrLine]) -> OcrHints:
        return parse_ocr(lines)
