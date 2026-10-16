"""Riot's Riftbound content API (`riftbound-content-v1`), the official source.

Needs an API key approved by Riot for a Riftbound product (`TCG_APITOKEN_GAMES_RFB_RIOT`);
development keys are refused (403). Limits: 20 requests/second, 100 per 2 minutes — one
request gives the whole catalog. Built from the published schema (RiftboundContentDTO:
sets[].cards[] with id, collectorNumber, set, name, subtitle, description, type, rarity,
faction, stats, art, flavorText, tags), not yet tried against the live API.
"""

from typing import Any

import httpx

from app.core.config import api_token
from app.core.http import get_with_retry
from app.games.riftbound.records import (
    RiftCard,
    as_int,
    dedupe,
    full_name,
    normalize_id,
    rules_text,
)

API_URL = "https://{region}.api.riotgames.com/riftbound/content/v1/contents"
REGION = "europe"


def token() -> str | None:
    return api_token("GAMES", "RIOT", "RFB")


async def fetch(http: httpx.AsyncClient, key: str) -> dict[str, Any]:
    response = await get_with_retry(
        http, API_URL.format(region=REGION), headers={"X-Riot-Token": key}
    )
    return response.json()


def _id(raw: dict[str, Any], set_code: str) -> str:
    """The card id (`OGN-066a` style ids become `ogn-066a`); without one, set and number."""
    if raw.get("id"):
        return normalize_id(str(raw["id"]))
    return f"{set_code.lower()}-{int(raw.get('collectorNumber') or 0):03d}"


def parse_content(content: dict[str, Any]) -> list[RiftCard]:
    cards = []
    for raw_set in content.get("sets") or []:
        set_code = str(raw_set.get("id") or "").upper()
        for raw in raw_set.get("cards") or []:
            if not raw.get("name"):
                continue
            stats = raw.get("stats") or {}
            art = raw.get("art") or {}
            faction = raw.get("faction")
            cards.append(
                RiftCard(
                    id=_id(raw, set_code),
                    set_code=str(raw.get("set") or set_code).upper(),
                    set_name=raw_set.get("name"),
                    name=full_name(raw["name"], raw.get("subtitle")),
                    rarity=raw.get("rarity"),
                    type=raw.get("type"),
                    domains=[d.strip().lower() for d in faction.split(",")] if faction else [],
                    energy=as_int(stats.get("energy")),
                    might=as_int(stats.get("might")),
                    power=as_int(stats.get("power")),
                    tags=list(raw.get("tags") or []),
                    text=rules_text(raw.get("description")),
                    flavor=raw.get("flavorText"),
                    artist=art.get("artist"),
                    image=art.get("fullURL") or art.get("thumbnailURL"),
                )
            )
    return dedupe(cards)
