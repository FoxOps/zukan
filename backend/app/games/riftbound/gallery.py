"""Riot's official Riftbound card gallery (playriftbound.com).

Each language page embeds its card list as JSON (`__NEXT_DATA__`): one download per
language, read the way a browser shows it — no page crawling. Used for what the APIs
lack: cards of sets they do not have yet and the Simplified Chinese edition (`zh-cn`, its
own names and pictures; other languages show the English cards).
"""

import json
import re
from typing import Any

import httpx

from app.core.http import get_with_retry
from app.games.riftbound.records import (
    RiftCard,
    as_int,
    dedupe,
    full_name,
    normalize_id,
    rules_text,
)

GALLERY_URL = "https://playriftbound.com/{locale}/card-gallery/"
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_CJK = re.compile(r"[一-鿿]")


async def fetch(http: httpx.AsyncClient, locale: str) -> list[dict[str, Any]]:
    response = await get_with_retry(
        http, GALLERY_URL.format(locale=locale), headers={"Accept": "text/html"}
    )
    return items(response.text)


def items(page: str) -> list[dict[str, Any]]:
    """Card entries of a gallery page."""
    match = _NEXT_DATA.search(page)
    if match is None:
        raise ValueError("Riftbound gallery: no card data in the page")
    blades = json.loads(match.group(1))["props"]["pageProps"]["page"]["blades"]
    return next(b["cards"]["items"] for b in blades if "cards" in b)


def _labels(field: dict[str, Any] | None, key: str = "values") -> list[str]:
    return [v["label"] for v in (field or {}).get(key) or [] if v.get("label")]


def _value(field: dict[str, Any] | None) -> Any:
    return ((field or {}).get("value") or {}).get("label")


def parse_card(raw: dict[str, Any]) -> RiftCard:
    card_set = (raw.get("set") or {}).get("value") or {}
    kind = raw.get("cardType") or {}
    # "New" marks cards Riot previewed before release.
    flags = raw.get("flags") or []
    return RiftCard(
        id=normalize_id(raw["id"]),
        set_code=card_set.get("id", "").upper() or raw["id"].split("-")[0].upper(),
        set_name=card_set.get("label"),
        name=full_name(raw["name"], raw.get("subtitle")),
        rarity=_value(raw.get("rarity")),
        type=next(iter(_labels(kind, "type")), None),
        supertype=next(iter(_labels(kind, "superType")), None),
        domains=[d.lower() for d in _labels(raw.get("domain"))],
        energy=as_int(_value(raw.get("energy"))),
        might=as_int(_value(raw.get("might"))),
        power=as_int(_value(raw.get("power"))),
        tags=list((raw.get("tags") or {}).get("tags") or []),
        text=rules_text(((raw.get("text") or {}).get("richText") or {}).get("body")),
        artist=next(iter(_labels(raw.get("illustrator"))), None),
        image=(raw.get("cardImage") or {}).get("url"),
        orientation=raw.get("orientation"),
        flags={"preview": True} if any(f.get("id") == "new" for f in flags) else {},
    )


def parse_cards(raw: list[dict[str, Any]]) -> list[RiftCard]:
    return dedupe([parse_card(item) for item in raw if item.get("id") and item.get("name")])


def chinese(raw: list[dict[str, Any]]) -> dict[str, tuple[str, str | None]]:
    """Simplified Chinese name and picture by card id; entries still in English (not
    translated yet) are left out."""
    out = {}
    for item in raw:
        name = full_name(item.get("name") or "", item.get("subtitle"), "，")
        if item.get("id") and _CJK.search(name):
            out[normalize_id(item["id"])] = (name, (item.get("cardImage") or {}).get("url"))
    return out
