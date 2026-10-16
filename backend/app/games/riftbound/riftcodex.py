"""Riftcodex (https://riftcodex.com), an open Riftbound card API: no key, English, card
images from Riot's CDN, TCGplayer ids, Cardmarket expansion ids per set.

`/sets` lists sets, `/cards?page=&size=100` the cards (about 15 pages)."""

import asyncio
from datetime import date, datetime
from typing import Any

import httpx

from app.core.http import get_with_retry
from app.games.riftbound.records import (
    RiftCard,
    as_int,
    dedupe,
    normalize_id,
    rules_text,
    split_variant,
)

API_URL = "https://api.riftcodex.com"
PAGE_SIZE = 100
# Pause between pages: an open API run by fans.
PAUSE = 0.2


async def fetch(http: httpx.AsyncClient) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(sets, cards) as the API gives them."""
    sets = (await get_with_retry(http, f"{API_URL}/sets", params={"size": PAGE_SIZE})).json()
    cards: list[dict[str, Any]] = []
    page = 1
    while True:
        params = {"page": page, "size": PAGE_SIZE}
        body = (await get_with_retry(http, f"{API_URL}/cards", params=params)).json()
        cards += body["items"]
        if page >= body.get("pages", 1):
            break
        page += 1
        await asyncio.sleep(PAUSE)
    return sets["items"], cards


def parse_card(raw: dict[str, Any]) -> RiftCard | None:
    if not raw.get("riftbound_id") or not raw.get("name"):
        return None
    name, variant = split_variant(raw["name"])
    kind = raw.get("classification") or {}
    stats = raw.get("attributes") or {}
    text = raw.get("text") or {}
    media = raw.get("media") or {}
    meta = raw.get("metadata") or {}
    return RiftCard(
        id=normalize_id(raw["riftbound_id"]),
        set_code=(raw.get("set") or {}).get("set_id", "").upper()
        or normalize_id(raw["riftbound_id"]).split("-")[0].upper(),
        set_name=(raw.get("set") or {}).get("label"),
        name=name,
        variant=variant,
        rarity=kind.get("rarity"),
        type=kind.get("type"),
        supertype=kind.get("supertype"),
        domains=[d.lower() for d in kind.get("domain") or []],
        energy=as_int(stats.get("energy")),
        might=as_int(stats.get("might")),
        power=as_int(stats.get("power")),
        tags=list(raw.get("tags") or []),
        text=rules_text(text.get("rich")) or text.get("plain"),
        flavor=text.get("flavour"),
        artist=media.get("artist"),
        image=media.get("image_url"),
        orientation=raw.get("orientation"),
        tcgplayer_id=str(raw["tcgplayer_id"]) if raw.get("tcgplayer_id") else None,
        flags={k: True for k in ("alternate_art", "overnumbered", "signature") if meta.get(k)},
    )


def parse_cards(raw: list[dict[str, Any]]) -> list[RiftCard]:
    return dedupe([card for item in raw if (card := parse_card(item)) is not None])


def set_release(raw: dict[str, Any]) -> date | None:
    value = raw.get("published_on")
    return datetime.fromisoformat(value).date() if value else None


def cardmarket_expansions(sets: list[dict[str, Any]]) -> dict[int, list[str]]:
    """Cardmarket expansion id -> our set codes. One expansion may group the promos of
    several sets."""
    out: dict[int, list[str]] = {}
    for raw in sets:
        ids = raw.get("cardmarket_id")
        for value in ids if isinstance(ids, list) else [ids]:
            if value and str(value).isdigit():
                out.setdefault(int(value), []).append(raw["set_id"].upper())
    return out
