"""Riftbound: League of Legends Trading Card Game (Riot Games).

Catalog: Riot's content API when an approved key is set (`riot.py`), else Riftcodex
(`riftcodex.py`, open API). Riot's official card gallery (`gallery.py`) adds the cards
those do not have yet (newest set) and the Simplified Chinese names and pictures.
Pictures all come from Riot's CDN, as Riot's policy for fan tools asks.

Printings are keyed on the Riftbound id (`ogn-066a-298`); cards on the full name
("Ahri, Alluring"), so alternate arts, signatures and promos of a card share one card.

Prices: Cardmarket's public price guide (game 22), matched by expansion and name.
"""

import logging
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx

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
    RarityDef,
    SetData,
)
from app.games.cardmarket import name_key
from app.games.ocr import bottom_part, by_position, clean, has_cjk, letter_ratio, script_language
from app.games.riftbound import gallery, riftcodex, riot
from app.games.riftbound.records import RiftCard, card_key, collector_number
from app.models import Printing

log = logging.getLogger(__name__)

CARDMARKET_GAME = 22
# Domain symbols of the official card gallery (Riot's CDN).
SYMBOLS = Path(__file__).parent / "symbols"
ICON_URL = "https://cmsassets.rgpub.io/sanity/images/dsfx7636/game_data_live"
LEGAL_NOTICE = (
    "Zukan isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot "
    "Games or anyone officially involved in producing or managing Riot Games properties. "
    "Riot Games, and all associated properties are trademarks or registered trademarks of "
    "Riot Games, Inc. Card data from Riftcodex and Riot Games' official card gallery."
)
# Rarities sold in both versions; the others are foil only.
_BOTH_FINISHES = {"common", "uncommon"}
# Printed collector line: "OGN • 066/298", "OGN-066a/298", "UNL · 229*/219", "VEN-SP3/006".
_CODE = re.compile(
    r"\b([A-Z]{2,4})\s*[-•·.・]?\s*([0-9]{1,3}[a-z*★]?|[A-Z]{1,2}[0-9]{1,2}[a-z]?)\s*/\s*([0-9]{2,3})\b",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"\b([A-Z]{2,4})\s*[-•·.]\s*([TR][0-9]{2}[a-z]?)\b", re.IGNORECASE)


def _icon(asset: str) -> str:
    return f"{ICON_URL}/{asset}-64x64.png"


def _finishes(rarity: str | None) -> list[str]:
    return ["normal", "foil"] if (rarity or "").casefold() in _BOTH_FINISHES else ["foil"]


def _set_data(code: str, raw: dict[str, Any] | None, cards: list[RiftCard]) -> SetData:
    name = (raw or {}).get("name") or next((c.set_name for c in cards if c.set_name), code)
    return SetData(
        external_id=code,
        code=code,
        name=name,
        release_date=riftcodex.set_release(raw) if raw else None,
        total=(raw or {}).get("card_count") or len(cards),
    )


def build_catalog(
    cards: list[RiftCard],
    extra: list[RiftCard] = (),  # type: ignore[assignment]
    chinese: dict[str, tuple[str, str | None]] | None = None,
    sets: list[dict[str, Any]] | None = None,
) -> CatalogBatch:
    """Catalog from the main source's `cards`, plus `extra` cards (gallery) it lacks and
    Chinese names and pictures by id."""
    chinese = chinese or {}
    known = {c.id for c in cards}
    everything = list(cards) + [c for c in extra if c.id not in known]
    raw_sets = {s["set_id"].upper(): s for s in sets or []}
    by_set: dict[str, list[RiftCard]] = {}
    for card in everything:
        by_set.setdefault(card.set_code, []).append(card)

    batch = CatalogBatch(
        sets=[_set_data(code, raw_sets.get(code), items) for code, items in by_set.items()]
    )
    by_card: dict[str, CardData] = {}
    for rc in everything:
        key = card_key(rc.name)
        card = by_card.get(key)
        if card is None:
            card = by_card[key] = CardData(
                external_id=key,
                name=rc.name,
                colors=rc.domains or ["colorless"],
                attributes={
                    "type": rc.type,
                    "supertype": rc.supertype,
                    "domains": rc.domains,
                    "energy": rc.energy,
                    "might": rc.might,
                    "power": rc.power,
                    "tags": rc.tags,
                    "text": rc.text,
                },
                names={"en": rc.name},
            )
        attributes: dict[str, Any] = {
            k: v
            for k, v in {
                "variant": rc.variant,
                "flavor": rc.flavor,
                "orientation": rc.orientation,
                **rc.flags,
            }.items()
            if v not in (None, "")
        }
        # From the rarity: TCGplayer's version list (tcgcsv) confirms them.
        attributes["finishes_guessed"] = True
        if rc.tcgplayer_id:
            attributes["market_ids"] = {"tcgplayer": rc.tcgplayer_id}
        printing = PrintingData(
            external_id=rc.id,
            set_external_id=rc.set_code,
            collector_number=collector_number(rc.id),
            rarity=rc.rarity,
            artist=rc.artist,
            finishes=_finishes(rc.rarity),
            languages=["en"],
            images={"en": rc.image} if rc.image else {},
            attributes=attributes,
        )
        zh = chinese.get(rc.id.split("~")[0])
        if zh:
            name, image = zh
            printing.languages.append("zh-hans")
            printing.names = {"zh-hans": name}
            if image:
                printing.images["zh-hans"] = image
        card.printings.append(printing)
    batch.cards = list(by_card.values())
    return batch


def _price_order(printing: PrintingData) -> tuple[bool, str]:
    """Plain printing of a name first, then alternate arts and specials, like Cardmarket's
    product ids."""
    special = (
        bool(printing.attributes.get("variant")) or not (printing.collector_number or "").isdigit()
    )
    return special, printing.external_id


# Catalog kept for card refreshes and price runs: (time.monotonic(), catalog, expansions).
CATALOG_TTL = 3600
_cached: tuple[float, CatalogBatch, dict[int, list[str]]] | None = None


class RiftboundProvider:
    id = "riftbound"
    name = "Riftbound"
    colors = [
        ColorDef("fury", "Fury", "#D7443E", _icon("5aeb4bfd203b5d265902f65aa5afae7da1682eaa")),
        ColorDef("calm", "Calm", "#4FA35B", _icon("b9ef2f5b74841ad11f3629aa381a76ac0187d007")),
        ColorDef("mind", "Mind", "#3A7BD5", _icon("17ab95a6bd052085b6803d846a287f625f347288")),
        ColorDef("body", "Body", "#E08A2E", _icon("7a5533034de5870808347bc4b296f0029bdd8eea")),
        ColorDef("chaos", "Chaos", "#8E4BC2", _icon("597ddb82be59e87b467c52bb10204f02c2005d06")),
        ColorDef("order", "Order", "#E3C04B", _icon("8bb1b193a8e1adc26ca28e1a21da8d1e2f5d2f72")),
        # Riot has no symbol for it: a gray diamond drawn for Zukan.
        ColorDef("colorless", "Colorless", "#9CA3AF", icon_file=SYMBOLS / "colorless.svg"),
    ]
    finishes = [FinishDef("normal", "Normal"), FinishDef("foil", "Foil")]
    languages = ["en", "zh-hans"]
    price_sources = ["cardmarket"]
    rarities = [
        RarityDef("common", "Common"),
        RarityDef("uncommon", "Uncommon"),
        RarityDef("rare", "Rare"),
        RarityDef("epic", "Epic"),
        RarityDef("showcase", "Showcase", ("Signed Showcase",)),
        RarityDef("promo", "Promo"),
    ]
    filters = [
        FilterDef("type", "Type", "type"),
        FilterDef("supertype", "Supertype", "supertype"),
        FilterDef("tags", "Tag", "tags"),
        FilterDef("rarity", "Rarity"),
    ]
    cardmarket_path = "Riftbound"
    short_names = ["riftbound", "rb", "rift"]
    # About 1500 printings, Riot's pictures: all cached locally.
    cache_all_images = True
    legal_notice = LEGAL_NOTICE
    text_attribute = "text"

    async def _catalog(self, http: httpx.AsyncClient) -> tuple[CatalogBatch, dict[int, list[str]]]:
        sets: list[dict[str, Any]] = []
        cards: list[RiftCard] | None = None
        if key := riot.token():
            try:
                cards = riot.parse_content(await riot.fetch(http, key))
            except httpx.HTTPError as exc:
                log.warning("Riot Riftbound API unavailable, using Riftcodex: %s", exc)
        try:
            sets, raw_cards = await riftcodex.fetch(http)
            if cards is None:
                cards = riftcodex.parse_cards(raw_cards)
        except httpx.HTTPError as exc:
            if cards is None:
                raise
            log.warning("Riftcodex unavailable: %s", exc)
        extra: list[RiftCard] = []
        chinese: dict[str, tuple[str, str | None]] = {}
        try:
            extra = gallery.parse_cards(await gallery.fetch(http, "en-us"))
            chinese = gallery.chinese(await gallery.fetch(http, "zh-cn"))
        except (httpx.HTTPError, ValueError, KeyError, StopIteration) as exc:
            # Page layout changed or site down: the APIs' cards are enough.
            log.warning("Riftbound gallery unavailable: %s", exc)
        return build_catalog(cards, extra, chinese, sets), riftcodex.cardmarket_expansions(sets)

    async def _cached_catalog(
        self, http: httpx.AsyncClient
    ) -> tuple[CatalogBatch, dict[int, list[str]]]:
        global _cached
        if _cached is None or time.monotonic() - _cached[0] > CATALOG_TTL:
            _cached = (time.monotonic(), *await self._catalog(http))
        return _cached[1], _cached[2]

    async def _cardmarket_quotes(
        self, http: httpx.AsyncClient, catalog: CatalogBatch, expansions: dict[int, list[str]]
    ) -> list[PriceQuote]:
        products = await cardmarket.products(http, CARDMARKET_GAME)
        guides = await cardmarket.price_guide(http, CARDMARKET_GAME)
        return cardmarket.match_products(
            catalog,
            products,
            guides,
            expansions,
            lambda finish: "" if finish == "normal" else "-foil",
            _price_order,
        )

    async def fetch_catalog(self, http: httpx.AsyncClient) -> AsyncIterator[CatalogBatch]:
        global _cached
        batch, expansions = await self._catalog(http)
        _cached = (time.monotonic(), batch, expansions)
        try:
            batch.prices = await self._cardmarket_quotes(http, batch, expansions)
        except httpx.HTTPError as exc:
            log.warning("Cardmarket price guide unavailable: %s", exc)
        yield batch

    async def fetch_prices(
        self, http: httpx.AsyncClient, owned: list[PriceTarget]
    ) -> AsyncIterator[list[PriceQuote]]:
        batch, expansions = await self._cached_catalog(http)
        yield await self._cardmarket_quotes(http, batch, expansions)

    async def fetch_cards(
        self, http: httpx.AsyncClient, cards: list[CardRef]
    ) -> AsyncIterator[CatalogBatch]:
        catalog, _ = await self._cached_catalog(http)
        wanted = {ref.external_id for ref in cards}
        found = [card for card in catalog.cards if card.external_id in wanted]
        if found:
            yield CatalogBatch(sets=catalog.sets, cards=found)

    async def lookup(self, http: httpx.AsyncClient, hints: OcrHints) -> CatalogBatch | None:
        """A scanned card missing from the catalog (newer than the last sync)."""
        catalog, _ = await self._cached_catalog(http)
        found = []
        key = name_key(hints.name) if hints.name else None
        for card in catalog.cards:
            numbered = (
                hints.set_code
                and hints.collector_number
                and any(
                    p.set_external_id == hints.set_code.upper()
                    and (p.collector_number or "").lstrip("0") == hints.collector_number.lstrip("0")
                    for p in card.printings
                )
            )
            if numbered or (key and name_key(card.name) == key):
                found.append(card)
        return CatalogBatch(sets=catalog.sets, cards=found) if found else None

    def image_file_stems(self, printing: Printing) -> list[str]:
        return []

    def parse_ocr(self, lines: list[OcrLine]) -> OcrHints:
        ordered = by_position([OcrLine(clean(line.text), line.left, line.top) for line in lines])
        text = " ".join(line.text for line in ordered)
        recognized = "riot games" in text.casefold() or "riftbound" in text.casefold()
        set_code = number = None
        for line in reversed(bottom_part(ordered) or ordered):
            match = _CODE.search(line.text) or _TOKEN.search(line.text)
            if match:
                set_code = match.group(1).upper()
                number = match.group(2).lower().replace("★", "*")
                recognized = True
                break
        lang = "zh-hans" if script_language(ordered) else "en"
        names = [
            line.text
            for line in ordered
            if len(line.text) >= 2
            and (has_cjk(line.text) or (len(line.text) >= 3 and letter_ratio(line.text) > 0.7))
            and not line.text.startswith("©")
            and not _CODE.search(line.text)
        ]
        return OcrHints(
            name=names[0] if names else None,
            other_names=names[1:3],
            set_code=set_code,
            collector_number=number,
            lang=lang,
            recognized=recognized,
        )
