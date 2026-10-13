"""Sorcery: Contested Realm, data from https://api.sorcerytcg.com (no prices).

The API lists one printing per finish; slugs look like `{set}-{card}-{product}-{finish}`,
e.g. `001-abundance-b-f`. Printings are grouped per set, card and product so finishes
become a list. Card images are not served by the API (its CDN must not be used); they
are imported from the public Google Drive folder, whose files are named after the
printing slug (`fudabako import-images sorcery DIR`).
"""

from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any

import httpx

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
from app.games.ocr import by_position, clean, letter_ratio
from app.models import Printing

API_URL = "https://api.sorcerytcg.com/api/cards"

_FINISHES = {"Standard": "standard", "Foil": "foil", "Rainbow": "rainbow"}
_ELEMENTS = ("air", "earth", "fire", "water")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _printing_key(slug: str) -> tuple[str, str]:
    """`001-abundance-b-f` -> set code `001`, printing id `abundance-b` (finish dropped)."""
    set_code, card_slug, product, _finish = slug.split("-")
    return set_code, f"{card_slug}-{product}"


def _card_attributes(engine: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": engine.get("type"),
        "category": engine.get("category"),
        "rarity": engine.get("rarity"),
        "rules": engine.get("rules"),
        "cost": engine.get("cost"),
        "attack": engine.get("attack"),
        "defense": engine.get("defense"),
        "life": engine.get("life"),
        "thresholds": {e: engine.get(e) or 0 for e in _ELEMENTS},
        "subtypes": engine.get("subtypes") or [],
        "keywords": engine.get("keywords") or [],
        "back": engine.get("back"),
    }


def parse_cards(raw: list[dict[str, Any]]) -> CatalogBatch:
    batch = CatalogBatch()
    sets: dict[str, SetData] = {}
    for item in raw:
        engine = item.get("engine") or {}
        elements = [e.lower() for e in engine.get("elements") or [] if e.lower() in _ELEMENTS]
        card = CardData(
            external_id=item["slug"],
            name=item["name"],
            colors=elements,
            attributes=_card_attributes(engine),
            names={"en": item["name"]},
        )
        printings: dict[tuple[str, str], PrintingData] = {}
        for raw_printing in item.get("printings") or []:
            set_info = raw_printing["set"]
            meta = raw_printing.get("meta") or {}
            set_code, printing_id = _printing_key(raw_printing["slug"])
            if set_code != set_info["code"]:
                raise ValueError(f"Unexpected Sorcery slug {raw_printing['slug']!r}")
            set_data = sets.setdefault(
                set_code,
                SetData(external_id=set_code, code=set_code, name=set_info["name"], lang="en"),
            )
            # Earliest printing date is the closest thing to a release date the API gives.
            printed = _parse_date(raw_printing.get("printedAt"))
            if printed and (set_data.release_date is None or printed < set_data.release_date):
                set_data.release_date = printed
            finish = _FINISHES.get(meta.get("finish"), str(meta.get("finish", "")).lower())
            printing = printings.get((set_code, printing_id))
            if printing is None:
                printing = printings[(set_code, printing_id)] = PrintingData(
                    external_id=printing_id,
                    set_external_id=set_code,
                    rarity=engine.get("rarity"),
                    artist=(meta.get("artist") or {}).get("name"),
                    languages=["en"],
                    attributes={
                        "product": meta.get("product"),
                        "typeline": meta.get("typeline"),
                        "flavor": meta.get("flavor"),
                        "back": meta.get("back"),
                        "slugs": {},
                    },
                )
            if finish not in printing.finishes:
                printing.finishes.append(finish)
            printing.attributes["slugs"][finish] = raw_printing["slug"]
        card.printings = list(printings.values())
        batch.cards.append(card)
    batch.sets = list(sets.values())
    return batch


class SorceryProvider:
    id = "sorcery"
    name = "Sorcery: Contested Realm"
    colors = [
        ColorDef("air", "Air", "#A7C7E7"),
        ColorDef("earth", "Earth", "#8B7355"),
        ColorDef("fire", "Fire", "#D9534F"),
        ColorDef("water", "Water", "#3B7DD8"),
    ]
    finishes = [
        FinishDef("standard", "Standard"),
        FinishDef("foil", "Foil"),
        FinishDef("rainbow", "Rainbow foil"),
    ]
    languages = ["en"]
    price_source = None

    async def fetch_catalog(self, http: httpx.AsyncClient) -> AsyncIterator[CatalogBatch]:
        # Whole catalog in one call (API limit: 30 requests/minute).
        response = await get_with_retry(http, API_URL)
        yield parse_cards(response.json())

    async def fetch_prices(
        self, http: httpx.AsyncClient, owned: list[PriceTarget]
    ) -> AsyncIterator[list[PriceQuote]]:
        return
        yield

    def image_file_stems(self, printing: Printing) -> list[str]:
        slugs: dict[str, str] = printing.attributes.get("slugs", {})
        # Prefer the standard finish image; foil scans look the same but shinier.
        order = ["standard", "foil", "rainbow"]
        return [slugs[f] for f in sorted(slugs, key=lambda f: order.index(f) if f in order else 9)]

    def parse_ocr(self, lines: list[OcrLine]) -> OcrHints:
        # No collector number or set code on the cards: the name (top line) is all.
        ordered = by_position([OcrLine(clean(line.text), line.left, line.top) for line in lines])
        names = [
            line.text
            for line in ordered
            if len(line.text) >= 3
            and letter_ratio(line.text) > 0.7
            and not line.text.startswith("©")
        ]
        recognized = any("Curiosa" in line.text for line in ordered)
        if not names:
            return OcrHints(lang="en", recognized=recognized)
        return OcrHints(name=names[0], other_names=names[1:3], lang="en", recognized=recognized)
