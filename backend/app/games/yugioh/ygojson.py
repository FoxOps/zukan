"""YGOJSON (github.com/iconmaster5326/YGOJSON, MIT): card names in every official
language and the printings of every locale, Japanese, Korean and Chinese (OCG) ones
included, gathered from Yugipedia and YGOPRODeck.

Released as `individual.zip` (one JSON file per card and per set, ~57 MB), read entry by
entry from a temporary file so the whole database never sits in memory. Its updates
stopped in 2026-04: newer cards come from YGOPRODeck and the Konami database.
"""

import asyncio
import json
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from app.games.yugioh.rarities import slug_name

URL = "https://github.com/iconmaster5326/YGOJSON/releases/download/v1/individual.zip"
# YGOJSON languages and locales to ours.
NAME_LANGS = {
    "en": "en",
    "fr": "fr",
    "de": "de",
    "it": "it",
    "pt": "pt",
    "es": "es",
    "ja": "ja",
    "ko": "ko",
    "zh-CN": "zh-hans",
    "zh-TW": "zh-hant",
}
EU_LOCALES = {"en": "en", "fr": "fr", "de": "de", "it": "it", "pt": "pt", "sp": "es"}
ASIAN_LOCALES = {"jp": "ja", "kr": "ko", "sc": "zh-hans", "tc": "zh-hant"}
EDITIONS = {"1st": "first", "unlimited": "unlimited", "limited": "limited"}


@dataclass
class YCard:
    uuid: str
    passwords: list[int]
    names: dict[str, str]
    attributes: dict[str, Any]


@dataclass
class YPrinting:
    card: str  # YCard.uuid
    number: str  # "BE2-JP001"
    rarity: str | None
    finishes: list[str]
    image: str | None


@dataclass
class YSet:
    external_id: str  # locale prefix, "BE2-JP"
    name: str
    lang: str
    release_date: date | None
    icon_url: str | None
    printings: list[YPrinting] = field(default_factory=list)


@dataclass
class YgoJson:
    cards: dict[str, YCard] = field(default_factory=dict)
    # OCG sets, one per set and Asian locale.
    sets: list[YSet] = field(default_factory=list)
    # Printings of European locales by (English number "LOB-EN001", rarity name):
    # languages they exist in and finishes.
    european: dict[tuple[str, str], tuple[list[str], list[str]]] = field(default_factory=dict)


async def download(http: httpx.AsyncClient, target: Path) -> None:
    async with http.stream("GET", URL, follow_redirects=True, timeout=300) as response:
        response.raise_for_status()
        with target.open("wb") as out:
            async for chunk in response.aiter_bytes(1 << 20):
                out.write(chunk)


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _card(raw: dict[str, Any]) -> YCard:
    texts = raw.get("text") or {}
    names = {
        NAME_LANGS[k]: v["name"] for k, v in texts.items() if k in NAME_LANGS and v.get("name")
    }
    attributes = {
        "card_type": raw.get("cardType"),
        "attribute": raw.get("attribute"),
        "race": raw.get("type"),
        "classifications": raw.get("classifications"),
        "level": raw.get("level") or raw.get("rank"),
        "atk": raw.get("atk"),
        "def": raw.get("def"),
        "desc": (texts.get("en") or {}).get("effect"),
    }
    return YCard(
        uuid=raw["id"],
        passwords=[int(p) for p in raw.get("passwords") or [] if str(p).isdigit()],
        names=names,
        attributes={k: v for k, v in attributes.items() if v not in (None, "", [])},
    )


def _read_set(raw: dict[str, Any], data: YgoJson) -> None:
    names = raw.get("name") or {}
    locales = raw.get("locales") or {}
    asian: dict[str, YSet] = {}
    for content in raw.get("contents") or []:
        finishes = [EDITIONS[e] for e in content.get("editions") or [] if e in EDITIONS]
        for loc in content.get("locales") or []:
            info = locales.get(loc) or {}
            prefix = info.get("prefix")
            if not prefix:
                continue
            images: dict[str, str] = {}
            for by_printing in (info.get("cardImages") or {}).values():
                for printing_id, url in by_printing.items():
                    images.setdefault(printing_id, url)
            # European locales are listed apart ("LOB-FR001"): one printing of the English
            # code, in several languages; editions of the English one.
            en_prefix = (locales.get("en") or {}).get("prefix")
            if loc in EU_LOCALES and en_prefix:
                for c in content.get("cards") or []:
                    rarity = slug_name(c.get("rarity"))
                    if not rarity:
                        continue
                    key = (f"{en_prefix}{c.get('suffix') or ''}", rarity)
                    langs, editions = data.european.setdefault(key, ([], []))
                    if EU_LOCALES[loc] not in langs:
                        langs.append(EU_LOCALES[loc])
                    if loc == "en" or not editions:
                        editions[:] = finishes
            if loc not in ASIAN_LOCALES:
                continue
            lang = ASIAN_LOCALES[loc]
            ys = asian.get(prefix)
            if ys is None:
                local = {"ja": "ja", "ko": "ko", "zh-hans": "zh-CN", "zh-hant": "zh-TW"}[lang]
                ys = asian[prefix] = YSet(
                    external_id=prefix,
                    name=names.get(local) or names.get("en") or prefix,
                    lang=lang,
                    release_date=_date(info.get("date")),
                    icon_url=None,
                )
            for c in content.get("cards") or []:
                ys.printings.append(
                    YPrinting(
                        card=c["card"],
                        number=f"{prefix}{c.get('suffix') or ''}",
                        rarity=slug_name(c.get("rarity")),
                        finishes=finishes or ["unlimited"],
                        image=images.get(c.get("id")),
                    )
                )
    data.sets.extend(s for s in asian.values() if s.printings)


def parse(path: Path) -> YgoJson:
    data = YgoJson()
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.endswith(".json") or "/" not in name:
                continue
            folder = name.split("/", 1)[0]
            if folder == "cards":
                card = _card(json.loads(archive.read(name)))
                data.cards[card.uuid] = card
            elif folder == "sets":
                _read_set(json.loads(archive.read(name)), data)
    return data


async def fetch(http: httpx.AsyncClient) -> YgoJson:
    with tempfile.TemporaryDirectory(prefix="zukan-ygojson-") as folder:
        path = Path(folder) / "individual.zip"
        await download(http, path)
        return await asyncio.to_thread(parse, path)
