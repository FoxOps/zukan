"""Magic: The Gathering, data from Scryfall (https://scryfall.com/docs/api).

Stale cards are fetched again with a search by oracle id (every printing in every
language, 175 per page).

The catalog comes from the `all_cards` bulk file (every printing in every language,
about 400 MB gzipped, streamed line by line). Scryfall stores one object per printing
and language; they are merged here into one printing per set and collector number.
English objects carry the full data, other languages are partial: they add a printed
name, a language and the scan of the card in that language.

Prices are Scryfall's Cardmarket EUR prices from the smaller `default_cards` file. The
daily price job adds Cardmarket's own price guide (lowest offer, average), matched by
the Cardmarket product id Scryfall gives.
"""

import asyncio
import json
import logging
import re
import zlib
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.http import get_with_retry
from app.games import cardmarket
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
    SetData,
)
from app.games.mtg import mtgjson
from app.games.ocr import (
    bottom_part,
    by_position,
    clean,
    letter_ratio,
    script_language,
    strip_number,
)
from app.models import Printing

log = logging.getLogger(__name__)

API_URL = "https://api.scryfall.com"
BATCH_SIZE = 2000
REQUEST_DELAY = 0.1

# Scryfall language codes to ours; other languages (Phyrexian, Hebrew...) are skipped.
LANGUAGES = {
    "en": "en",
    "fr": "fr",
    "de": "de",
    "it": "it",
    "es": "es",
    "pt": "pt",
    "ja": "ja",
    "ko": "ko",
    "zhs": "zh-hans",
    "zht": "zh-hant",
    "ru": "ru",
}
PRICE_FIELDS = {"nonfoil": "eur", "foil": "eur_foil"}
USD_FIELDS = {"nonfoil": "usd", "foil": "usd_foil", "etched": "usd_etched"}
# Price guide field suffix per finish.
GUIDE_SUFFIXES = {"nonfoil": "", "foil": "-foil"}
CARDMARKET_GAME = 1
# Mana symbols, as served by Scryfall's symbology API.
SYMBOLS_URL = "https://svgs.scryfall.io/card-symbols"


class MtgSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TCG_MTG_", env_file=".env", extra="ignore")

    # `all_cards` includes translated names (needed to scan non-English cards);
    # `default_cards` is 5x smaller but English (or the only printed language) only.
    catalog_bulk: str = "all_cards"


def _decimal(value: str | None) -> Decimal | None:
    return Decimal(value) if value else None


def parse_set(raw: dict[str, Any]) -> SetData:
    released = raw.get("released_at")
    return SetData(
        external_id=raw["code"],
        code=raw["code"].upper(),
        name=raw["name"],
        release_date=date.fromisoformat(released) if released else None,
        total=raw.get("card_count"),
        icon_url=raw.get("icon_svg_uri"),
    )


def _oracle_id(raw: dict[str, Any]) -> str | None:
    if raw.get("oracle_id"):
        return raw["oracle_id"]
    faces = raw.get("card_faces") or [{}]
    return faces[0].get("oracle_id")


def _colors(raw: dict[str, Any]) -> list[str]:
    if "colors" in raw:
        colors = raw["colors"]
    else:
        colors = [c for face in raw.get("card_faces", []) for c in face.get("colors", [])]
    ordered = [c for c in "WUBRG" if c in colors]
    return ordered or ["C"]


def _face_images(raw: dict[str, Any]) -> list[str]:
    # Scryfall shows the English scan (or nothing) when it has no scan in this language.
    if raw.get("image_status") in ("missing", "placeholder"):
        return []
    if raw.get("image_uris"):
        return [raw["image_uris"]["normal"]]
    return [f["image_uris"]["normal"] for f in raw.get("card_faces", []) if f.get("image_uris")]


def _printed_name(raw: dict[str, Any]) -> str | None:
    if raw.get("printed_name"):
        return raw["printed_name"]
    faces = [f.get("printed_name") for f in raw.get("card_faces", [])]
    if faces and all(faces):
        return " // ".join(faces)
    return None


def parse_type_line(type_line: str) -> tuple[list[str], list[str]]:
    """Types (with supertypes) and subtypes of every face: "Legendary Creature — Elf
    Druid" gives (["Legendary", "Creature"], ["Elf", "Druid"])."""
    types: dict[str, None] = {}
    subtypes: dict[str, None] = {}
    for face in type_line.split(" // "):
        left, _, right = face.partition("—")
        types |= dict.fromkeys(left.split())
        subtypes |= dict.fromkeys(right.split())
    return list(types), list(subtypes)


_CARD_FIELDS = ("mana_cost", "cmc", "type_line", "oracle_text", "power", "toughness", "loyalty")
_FACE_FIELDS = ("name", "mana_cost", "type_line", "oracle_text", "power", "toughness", "loyalty")


def parse_card(raw: dict[str, Any]) -> CardData | None:
    """Turn one Scryfall card object into a card with one printing (None = skipped)."""
    lang = LANGUAGES.get(raw.get("lang", ""))
    oracle_id = _oracle_id(raw)
    if raw.get("digital") or lang is None or oracle_id is None:
        return None

    attributes: dict[str, Any] = {k: raw[k] for k in _CARD_FIELDS if raw.get(k) is not None}
    attributes["types"], attributes["subtypes"] = parse_type_line(raw.get("type_line") or "")
    attributes["layout"] = raw.get("layout")
    attributes["color_identity"] = raw.get("color_identity", [])
    if raw.get("card_faces"):
        attributes["faces"] = [
            {k: face[k] for k in _FACE_FIELDS if face.get(k) is not None}
            for face in raw["card_faces"]
        ]

    english = lang == "en"
    images = _face_images(raw)
    printing_attributes: dict[str, Any] = {}
    if english:
        printing_attributes["scryfall_id"] = raw["id"]
        market_ids = {
            source: raw[key]
            for source, key in (("cardmarket", "cardmarket_id"), ("tcgplayer", "tcgplayer_id"))
            if raw.get(key)
        }
        if market_ids:
            printing_attributes["market_ids"] = market_ids
    if len(images) > 1:
        printing_attributes["back_image_url"] = images[1]

    printed = _printed_name(raw)
    printing = PrintingData(
        external_id=raw["collector_number"],
        set_external_id=raw["set"],
        collector_number=raw["collector_number"],
        rarity=raw.get("rarity"),
        artist=raw.get("artist"),
        finishes=list(raw.get("finishes", [])),
        languages=[lang],
        images={lang: images[0]} if images else {},
        attributes=printing_attributes,
        names={lang: printed} if printed and printed != raw["name"] else {},
    )
    return CardData(
        external_id=oracle_id,
        name=raw["name"],
        colors=_colors(raw),
        attributes=attributes,
        printings=[printing],
        names={"en": raw["name"]},
        partial=not english,
    )


def parse_prices(
    raw: dict[str, Any], guides: dict[int, cardmarket.Guide] | None = None
) -> list[PriceQuote]:
    """Scryfall's Cardmarket trend price, with lowest offer and average from Cardmarket's
    price guide when given, and TCGplayer's market price."""
    prices = raw.get("prices") or {}
    guide = (guides or {}).get(raw.get("cardmarket_id") or 0)
    quotes = []
    for finish, field in PRICE_FIELDS.items():
        if finish not in raw.get("finishes", []):
            continue
        trend, low, avg = _decimal(prices.get(field)), None, None
        if guide is not None:
            guide_trend, low, avg = cardmarket.prices(guide, GUIDE_SUFFIXES[finish])
            trend = trend or guide_trend
        if trend is not None:
            quotes.append(
                PriceQuote(
                    raw["set"],
                    raw["collector_number"],
                    finish,
                    trend,
                    low=low,
                    avg=avg,
                    source="cardmarket",
                )
            )
    for finish, field in USD_FIELDS.items():
        if finish in raw.get("finishes", []) and (usd := _decimal(prices.get(field))):
            quotes.append(
                PriceQuote(
                    raw["set"],
                    raw["collector_number"],
                    finish,
                    usd,
                    currency="USD",
                    source="tcgplayer",
                )
            )
    return quotes


async def iter_jsonl_gz(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """Decode a gzipped JSON Lines body while it downloads."""
    decompressor = zlib.decompressobj(wbits=zlib.MAX_WBITS | 32)  # gzip or zlib header
    pending = b""
    async for chunk in response.aiter_raw():
        pending += decompressor.decompress(chunk)
        *lines, pending = pending.split(b"\n")
        for line in lines:
            if line.strip():
                yield json.loads(line)
    pending += decompressor.flush()
    if pending.strip():
        yield json.loads(pending)


# Language codes printed in the collector line ("DOM • EN").
PRINTED_LANGUAGES = {
    "EN": "en", "FR": "fr", "DE": "de", "IT": "it", "ES": "es", "SP": "es", "PT": "pt",
    "JP": "ja", "JA": "ja", "KO": "ko", "KR": "ko", "RU": "ru", "CS": "zh-hans", "CT": "zh-hant",
}  # fmt: skip
_SET_LANG = re.compile(r"\b([A-Z0-9]{3,5})\s*[•·.*+\-]?\s*(" + "|".join(PRINTED_LANGUAGES) + r")\b")
# Collector number over set size; the size filter tells it from power/toughness ("1/1").
_NUMBER_TOTAL = re.compile(r"\b(\d{1,4}[a-z★*]?)\s*/\s*(\d{2,4})\b")
MIN_SET_SIZE = 20
# Since 2023 the total is gone: "0123 R" or "R 0123".
_NUMBER_RARITY = re.compile(
    r"(?:^|\s)(?:[CURMSLTP]\s+)?(\d{3,4}[a-z★*]?)(?:\s+[CURMSLTP])?(?:\s|$)"
)
_MARKERS = re.compile(r"Wizards of the Coast|Wizards|™ ?& ?©", re.IGNORECASE)
_MANA_TAIL = re.compile(r"(\s+[\dWUBRGCXP{}()@®©*]{1,4})+$")


def parse_ocr(lines: list[OcrLine]) -> OcrHints:
    ordered = by_position([OcrLine(clean(line.text), line.left, line.top) for line in lines])
    hints = OcrHints()
    bottom = bottom_part(ordered)
    for line in bottom:
        if hints.set_code is None and (match := _SET_LANG.search(line.text)):
            if not match.group(1).isdigit():
                hints.set_code = match.group(1)
                hints.lang = PRINTED_LANGUAGES[match.group(2)]
    # Power/toughness sits bottom right, collector info bottom left; old frames end the
    # copyright line with it, which ML Kit may return as a block of its own on the right.
    on_left = [line for line in bottom if line.left is None or line.left < 0.6]
    for line in on_left + [line for line in bottom if line not in on_left]:
        match = _NUMBER_TOTAL.search(line.text)
        if match and int(match.group(2)) >= MIN_SET_SIZE:
            hints.collector_number = match.group(1)
            break
    if hints.collector_number is None:
        for line in bottom:
            if hints.set_code and hints.set_code in line.text:
                continue
            if _MARKERS.search(line.text) or "©" in line.text:
                continue  # copyright years are not collector numbers
            if match := _NUMBER_RARITY.search(line.text):
                hints.collector_number = match.group(1)
                break
    if hints.collector_number:
        hints.collector_number = strip_number(hints.collector_number.replace("*", "★"))
    names = [
        _MANA_TAIL.sub("", line.text).strip()
        for line in ordered
        if line not in bottom and letter_ratio(line.text) > 0.6 and len(line.text) >= 2
    ]
    names = [n for n in names if len(n) >= 2]
    if names:
        hints.name, hints.other_names = names[0], names[1:3]
    hints.lang = hints.lang or script_language(lines)
    text = " ".join(line.text for line in ordered)
    hints.recognized = hints.set_code is not None or bool(_MARKERS.search(text))
    return hints


class MtgProvider:
    id = "mtg"
    name = "Magic: The Gathering"
    colors = [
        ColorDef("W", "White", "#F8E7B9", icon_url=f"{SYMBOLS_URL}/W.svg"),
        ColorDef("U", "Blue", "#0E68AB", icon_url=f"{SYMBOLS_URL}/U.svg"),
        ColorDef("B", "Black", "#150B00", icon_url=f"{SYMBOLS_URL}/B.svg"),
        ColorDef("R", "Red", "#D3202A", icon_url=f"{SYMBOLS_URL}/R.svg"),
        ColorDef("G", "Green", "#00733E", icon_url=f"{SYMBOLS_URL}/G.svg"),
        ColorDef("C", "Colorless", "#A9A9A9", icon_url=f"{SYMBOLS_URL}/C.svg"),
    ]
    finishes = [
        FinishDef("nonfoil", "Standard"),
        FinishDef("foil", "Foil"),
        FinishDef("etched", "Etched foil"),
    ]
    languages = list(LANGUAGES.values())
    price_sources = ["cardmarket", "tcgplayer"]
    cardmarket_path = "Magic"
    secondary_sources = [mtgjson.source]
    filters = [
        FilterDef("types", "Type", "types"),
        FilterDef("subtypes", "Subtype", "subtypes"),
        FilterDef("rarity", "Rarity"),
    ]
    # 2: card types and subtypes (advanced search).
    catalog_version = 2
    short_names = ["mtg", "magic"]

    async def _bulk(self, http: httpx.AsyncClient, kind: str) -> AsyncIterator[dict[str, Any]]:
        meta = (await get_with_retry(http, f"{API_URL}/bulk-data/{kind}")).json()
        url = meta["jsonl_download_uri"]
        log.info("Downloading Scryfall %s (%s bytes)", kind, meta.get("compressed_size"))
        async with http.stream("GET", url, headers={"Accept": "*/*"}) as response:
            response.raise_for_status()
            async for raw in iter_jsonl_gz(response):
                yield raw

    async def _sets(self, http: httpx.AsyncClient) -> list[SetData]:
        raw_sets = (await get_with_retry(http, f"{API_URL}/sets")).json()["data"]
        return [parse_set(s) for s in raw_sets if not s.get("digital")]

    async def _search(self, http: httpx.AsyncClient, query: str) -> AsyncIterator[dict[str, Any]]:
        """Every printing, in every language, matching a Scryfall search."""
        url: str | None = f"{API_URL}/cards/search"
        params: dict[str, str] | None = {
            "q": query,
            "unique": "prints",
            "include_multilingual": "true",
        }
        while url:
            try:
                page = (await get_with_retry(http, url, params=params)).json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:  # no match
                    return
                raise
            for raw in page.get("data", []):
                yield raw
            url, params = (page.get("next_page"), None) if page.get("has_more") else (None, None)
            # Scryfall asks for 50-100 ms between requests.
            await asyncio.sleep(REQUEST_DELAY)

    def _batch(self, raws: list[dict[str, Any]], sets: dict[str, SetData]) -> CatalogBatch:
        batch = CatalogBatch()
        used: set[str] = set()
        for raw in raws:
            card = parse_card(raw)
            if card is None or raw["set"] not in sets:
                continue
            batch.cards.append(card)
            batch.prices += parse_prices(raw)
            used.add(raw["set"])
        batch.sets = [sets[code] for code in sorted(used)]
        return batch

    async def fetch_cards(
        self, http: httpx.AsyncClient, cards: list[CardRef]
    ) -> AsyncIterator[CatalogBatch]:
        sets = {s.external_id: s for s in await self._sets(http)}
        for ref in cards:
            raws = [raw async for raw in self._search(http, f"oracleid:{ref.external_id}")]
            batch = self._batch(raws, sets)
            if batch.cards:
                yield batch

    async def fetch_catalog(self, http: httpx.AsyncClient) -> AsyncIterator[CatalogBatch]:
        sets = await self._sets(http)
        known = {s.external_id for s in sets}
        yield CatalogBatch(sets=sets)

        batch = CatalogBatch()
        async for raw in self._bulk(http, MtgSettings().catalog_bulk):
            card = parse_card(raw)
            if card is None or raw["set"] not in known:
                continue
            batch.cards.append(card)
            # Usually only English objects have prices, except language-only printings.
            batch.prices += parse_prices(raw)
            if len(batch.cards) >= BATCH_SIZE:
                yield batch
                batch = CatalogBatch()
        if batch.cards:
            yield batch

    async def fetch_prices(
        self, http: httpx.AsyncClient, owned: list[PriceTarget]
    ) -> AsyncIterator[list[PriceQuote]]:
        # The bulk file has every price, cheaper than looking up owned cards one by one.
        try:
            guides = await cardmarket.price_guide(http, CARDMARKET_GAME)
        except httpx.HTTPError as exc:
            log.warning("Cardmarket price guide unavailable, trend prices only: %s", exc)
            guides = {}
        quotes: list[PriceQuote] = []
        async for raw in self._bulk(http, "default_cards"):
            if raw.get("digital"):
                continue
            quotes += parse_prices(raw, guides)
            if len(quotes) >= BATCH_SIZE:
                yield quotes
                quotes = []
        if quotes:
            yield quotes

    def image_file_stems(self, printing: Printing) -> list[str]:
        return []

    def parse_ocr(self, lines: list[OcrLine]) -> OcrHints:
        return parse_ocr(lines)
