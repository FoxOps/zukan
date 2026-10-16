"""Disney Lorcana Trading Card Game (Ravensburger).

Catalog: LorcanaJSON (lorcanajson.org), Ravensburger's official card data in English,
French, German and Italian (one `allCards.json` per language, pictures on Ravensburger's
servers, Cardmarket and TCGplayer ids). Chosen over Lorcast (English only, plus TCGplayer
prices tcgcsv already gives) and lorcana-api.com / api-lorcana.com (less data). No source
has the Japanese or Chinese printings yet.

Cards are keyed on their full name ("Ariel - On Human Legs"): enchanted, epic, iconic and
promo printings of a card share it. Printings are keyed on LorcanaJSON's card id, the same
in every language. Promos go to a set per promo group ("P1", "D23"...).

Prices: Cardmarket's public price guide (game 19) by the Cardmarket id LorcanaJSON gives,
TCGplayer from tcgcsv (gap source, TCGplayer ids).
"""

import logging
import re
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import httpx

from app.core.http import get_with_retry
from app.games import cardmarket
from app.games.base import (
    CardData,
    CatalogBatch,
    ColorDef,
    FilterDef,
    FinishDef,
    OcrHints,
    OcrLine,
    PriceQuote,
    PriceTarget,
    PrintingData,
    RarityDef,
    SetData,
)
from app.games.ocr import by_position, clean, letter_ratio
from app.models import Printing

log = logging.getLogger(__name__)

DATA_URL = "https://lorcanajson.org/files/current/{lang}/allCards.json"
CARDMARKET_GAME = 19
LANGUAGES = ["en", "fr", "de", "it"]
LEGAL_NOTICE = (
    "Disney Lorcana is a trademark of Disney; the game is published by Ravensburger. Zukan "
    "is not produced, endorsed, supported or affiliated with Disney or Ravensburger. Card "
    "data from LorcanaJSON."
)
# Printed collector line: "205/204 • EN • 1", "4a/204 • EN • 3", "TFC • EN • 1/P1".
_LINE = re.compile(
    r"\b([0-9]{1,3}[a-z]?)\s*/\s*([0-9]{1,3}|[A-Z]{1,3}[0-9]?)\s*[•·.]\s*(EN|FR|DE|IT|JA|ZH)\s*[•·.]\s*([0-9]{1,2}|Q[0-9])\b",
    re.IGNORECASE,
)
_PROMO_LINE = re.compile(
    r"\b(EN|FR|DE|IT)\s*[•·.]\s*([0-9]{1,3})\s*/\s*([A-Z]{1,3}[0-9]{0,2})\b", re.IGNORECASE
)
_INKS = {"amber", "amethyst", "emerald", "ruby", "sapphire", "steel"}


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _finishes(foil_types: list[str]) -> list[str]:
    finishes = []
    if "None" in foil_types or not foil_types:
        finishes.append("normal")
    if any(f != "None" for f in foil_types):
        finishes.append("foil")
    return finishes


def _colors(raw: dict[str, Any]) -> list[str]:
    inks = raw.get("colors") or (raw.get("color") or "").split("-")
    return [ink.casefold() for ink in inks if ink.casefold() in _INKS]


def _set_of(raw: dict[str, Any]) -> str:
    return raw.get("promoGrouping") or raw["setCode"]


def _number(raw: dict[str, Any]) -> str:
    return f"{raw['number']}{raw.get('variant') or ''}"


def build_catalog(by_lang: dict[str, dict[str, Any]]) -> CatalogBatch:
    """Catalog from LorcanaJSON files by language (English first)."""
    english = by_lang["en"]
    sets: dict[str, SetData] = {}
    for code, raw in english.get("sets", {}).items():
        sets[code] = SetData(
            external_id=code,
            code=code,
            name=raw.get("name") or code,
            lang="en",
            release_date=_date(raw.get("releaseDate")),
            total=(raw.get("cardCounts") or {}).get("base") or None,
        )
    translated = {
        lang: {c["id"]: c for c in data.get("cards", [])}
        for lang, data in by_lang.items()
        if lang != "en"
    }
    cards: dict[str, CardData] = {}
    for raw in english.get("cards", []):
        key = raw["fullName"].casefold()
        card = cards.get(key)
        if card is None:
            card = cards[key] = CardData(
                external_id=key,
                name=raw["fullName"],
                colors=_colors(raw),
                attributes={
                    k: v
                    for k, v in {
                        "type": raw.get("type"),
                        "classifications": raw.get("subtypes"),
                        "story": raw.get("story"),
                        "cost": raw.get("cost"),
                        "inkable": "Inkable" if raw.get("inkwell") else "Uninkable",
                        "strength": raw.get("strength"),
                        "willpower": raw.get("willpower"),
                        "lore": raw.get("lore"),
                        "move_cost": raw.get("moveCost"),
                        "text": raw.get("fullText"),
                    }.items()
                    if v not in (None, "", [])
                },
                names={"en": raw["fullName"]},
            )
        set_code = _set_of(raw)
        if set_code not in sets:
            sets[set_code] = SetData(
                external_id=set_code,
                code=set_code,
                name=f"Promos {set_code}",
                lang="en",
                release_date=_date(raw.get("allowedInTournamentsFromDate")),
            )
        links = raw.get("externalLinks") or {}
        market_ids = {
            k: v
            for k, v in {
                "cardmarket": links.get("cardmarketId"),
                "tcgplayer": links.get("tcgPlayerId"),
            }.items()
            if v
        }
        foil_types = raw.get("foilTypes") or []
        attributes: dict[str, Any] = {"market_ids": market_ids} if market_ids else {}
        special = [f for f in foil_types if f not in ("None", "Silver")]
        if special:
            attributes["foil_type"] = ", ".join(special)
        if raw.get("varnishType"):
            attributes["varnish"] = raw["varnishType"]
        if raw.get("flavorText"):
            attributes["flavor"] = raw["flavorText"]
        printing = PrintingData(
            external_id=str(raw["id"]),
            set_external_id=set_code,
            collector_number=_number(raw)
            if not raw.get("promoGrouping")
            else f"{raw['number']}/{raw['promoGrouping']}",
            rarity=raw.get("rarity"),
            artist=raw.get("artistsText"),
            finishes=_finishes(foil_types),
            languages=["en"],
            images={"en": raw["images"]["full"]} if (raw.get("images") or {}).get("full") else {},
            attributes=attributes,
        )
        for lang, cards_of in translated.items():
            other = cards_of.get(raw["id"])
            if other is None:
                continue
            printing.languages.append(lang)
            if other.get("fullName"):
                card.names.setdefault(lang, other["fullName"])
            if (other.get("images") or {}).get("full"):
                printing.images[lang] = other["images"]["full"]
        card.printings.append(printing)
    used = {p.set_external_id for c in cards.values() for p in c.printings}
    return CatalogBatch(
        sets=[s for s in sets.values() if s.external_id in used], cards=list(cards.values())
    )


def cardmarket_quotes(
    catalog: CatalogBatch, guides: dict[int, cardmarket.Guide]
) -> list[PriceQuote]:
    quotes = []
    for card in catalog.cards:
        for printing in card.printings:
            product = (printing.attributes.get("market_ids") or {}).get("cardmarket")
            guide = guides.get(product) if product else None
            if guide is None:
                continue
            for finish in printing.finishes:
                suffix = "-foil" if finish == "foil" else ""
                trend, low, avg = cardmarket.prices(guide, suffix)
                if trend is None and finish == "foil" and printing.finishes == ["foil"]:
                    # Foil-only cards (enchanted...) are priced as plain products.
                    trend, low, avg = cardmarket.prices(guide)
                if trend is None:
                    continue
                quotes.append(
                    PriceQuote(
                        printing.set_external_id,
                        printing.external_id,
                        finish,
                        trend=trend,
                        low=low,
                        avg=avg,
                        source="cardmarket",
                    )
                )
    return quotes


class LorcanaProvider:
    id = "lorcana"
    name = "Disney Lorcana"
    colors = [
        ColorDef("amber", "Amber", "#F2B32E"),
        ColorDef("amethyst", "Amethyst", "#7E4A9C"),
        ColorDef("emerald", "Emerald", "#2E8B57"),
        ColorDef("ruby", "Ruby", "#C8243B"),
        ColorDef("sapphire", "Sapphire", "#1F6FB5"),
        ColorDef("steel", "Steel", "#8A949E"),
    ]
    finishes = [FinishDef("normal", "Normal"), FinishDef("foil", "Foil")]
    rarities = [
        RarityDef("common", "Common"),
        RarityDef("uncommon", "Uncommon"),
        RarityDef("rare", "Rare"),
        RarityDef("super_rare", "Super Rare", ("Super_rare",)),
        RarityDef("legendary", "Legendary"),
        RarityDef("epic", "Epic"),
        RarityDef("enchanted", "Enchanted"),
        RarityDef("iconic", "Iconic"),
        RarityDef("special", "Special", ("Promo",)),
    ]
    languages = LANGUAGES
    price_sources = ["cardmarket", "tcgplayer"]
    filters = [
        FilterDef("type", "Type", "type"),
        FilterDef("classifications", "Classification", "classifications"),
        FilterDef("story", "Story", "story"),
        FilterDef("inkable", "Inkwell", "inkable"),
        FilterDef("rarity", "Rarity"),
    ]
    cardmarket_path = "Lorcana"
    short_names = ["lorcana", "lor"]
    # About 3500 printings: every picture is cached.
    cache_all_images = True
    legal_notice = LEGAL_NOTICE
    text_attribute = "text"
    source_keys = {"tcgcsv": 71, "tcgapi_eu": "lorcana", "apitcg": "lorcana"}

    async def _files(self, http: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
        files = {}
        for lang in LANGUAGES:
            try:
                response = await get_with_retry(http, DATA_URL.format(lang=lang))
                files[lang] = response.json()
            except httpx.HTTPError as exc:
                if lang == "en":
                    raise
                log.warning("LorcanaJSON %s unavailable: %s", lang, exc)
        return files

    async def _quotes(self, http: httpx.AsyncClient, catalog: CatalogBatch) -> list[PriceQuote]:
        return cardmarket_quotes(catalog, await cardmarket.price_guide(http, CARDMARKET_GAME))

    async def fetch_catalog(self, http: httpx.AsyncClient) -> AsyncIterator[CatalogBatch]:
        batch = build_catalog(await self._files(http))
        try:
            batch.prices = await self._quotes(http, batch)
        except httpx.HTTPError as exc:
            log.warning("Cardmarket price guide unavailable: %s", exc)
        yield batch

    async def fetch_prices(
        self, http: httpx.AsyncClient, owned: list[PriceTarget]
    ) -> AsyncIterator[list[PriceQuote]]:
        response = await get_with_retry(http, DATA_URL.format(lang="en"))
        yield await self._quotes(http, build_catalog({"en": response.json()}))

    def image_file_stems(self, printing: Printing) -> list[str]:
        return []

    def parse_ocr(self, lines: list[OcrLine]) -> OcrHints:
        ordered = by_position([OcrLine(clean(line.text), line.left, line.top) for line in lines])
        text = " ".join(line.text for line in ordered)
        recognized = "disney" in text.casefold() or "ravensburger" in text.casefold()
        set_code = number = lang = None
        for line in reversed(ordered):
            if match := _LINE.search(line.text):
                number, lang, set_code = match.group(1).lower(), match.group(3), match.group(4)
            elif match := _PROMO_LINE.search(line.text):
                lang, number, set_code = match.group(1), match.group(2), match.group(3)
                number = f"{number}/{set_code.upper()}"
            else:
                continue
            recognized = True
            break
        names = [
            line.text
            for line in ordered
            if len(line.text) >= 3
            and letter_ratio(line.text) > 0.7
            and not _LINE.search(line.text)
            and not line.text.startswith("©")
        ]
        return OcrHints(
            name=names[0] if names else None,
            other_names=names[1:3],
            set_code=set_code.upper() if set_code else None,
            collector_number=number,
            lang=lang.lower() if lang else None,
            recognized=recognized,
        )
