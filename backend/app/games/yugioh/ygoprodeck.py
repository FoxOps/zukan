"""YGOPRODeck API (db.ygoprodeck.com/api/v7): every TCG card in one download.

`cardinfo.php` lists cards (password `id`, type, attribute, texts, artworks), each with
its TCG printings (`card_sets`: set code "LOB-EN001", rarity, TCGplayer price in USD);
`cardsets.php` the sets (code "LOB", name, date, picture). `language=fr|de|it|pt` gives
the same cards with translated names. YGOPRODeck allows 20 requests a second and asks
that pictures be downloaded and served locally (never linked to): the image cache does.
"""

from typing import Any

import httpx

from app.core.http import get_with_retry

API_URL = "https://db.ygoprodeck.com/api/v7"
# Translated listings YGOPRODeck has (names only are kept).
LANGUAGES = ("fr", "de", "it", "pt")


async def cards(http: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Every card, with `misc_info` (Konami id, release dates)."""
    response = await get_with_retry(http, f"{API_URL}/cardinfo.php", params={"misc": "yes"})
    return response.json()["data"]


async def sets(http: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await get_with_retry(http, f"{API_URL}/cardsets.php")
    return response.json()


async def names(http: httpx.AsyncClient, lang: str) -> dict[int, str]:
    """Card names in `lang` by password."""
    response = await get_with_retry(http, f"{API_URL}/cardinfo.php", params={"language": lang})
    return {c["id"]: c["name"] for c in response.json()["data"] if c.get("name")}


def misc(card: dict[str, Any]) -> dict[str, Any]:
    info = card.get("misc_info") or [{}]
    return info[0] if info else {}
