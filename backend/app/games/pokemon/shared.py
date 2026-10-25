"""What the Asian and Chinese Pokémon games need from the international one, read from
TCGdex's listings (cheap: one request per language) and kept a few hours:

- international set ids: an Asian set reusing one is stored as `asia:<id>`;
- English card keys: Asian cards named after species join the English card's key
  ("ルギアV" is "en:lugia v"), so their printings group like the international ones;
- the international names of each English card (same TCGdex card id in every language):
  an Asian card known by its English name is shown in the reader's language
  ("보스의 지령" is "Boss's Orders", "Ordres du Boss").

Digital sets (Pokémon TCG Pocket) and their cards are left out, as the international
catalog skips them.
"""

import asyncio
import time
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field

import httpx

from app.core.http import get_with_retry

TTL = 6 * 3600
# TCGdex languages of the international game.
INTERNATIONAL = ["en", "fr", "de", "it", "es", "pt"]


@dataclass(frozen=True)
class International:
    set_ids: frozenset[str]
    english_cards: frozenset[str]
    # Normalised English card key -> {language: name} in the other international languages.
    latin_names: Mapping[str, Mapping[str, str]] = field(default_factory=dict)


_cached: tuple[float, International] | None = None
_lock = asyncio.Lock()


async def _get(http: httpx.AsyncClient, url: str, missing=None):
    """The JSON at `url`; `missing` when TCGdex has nothing there."""
    try:
        return (await get_with_retry(http, url)).json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise
        return missing


async def _read(http: httpx.AsyncClient, api_url: str, digital_series: set[str]) -> International:
    from app.games.pokemon.provider import card_key
    from app.games.pokemon.species import normalize_name

    digital: set[str] = set()
    for serie in digital_series:
        raw = await _get(http, f"{api_url}/en/series/{serie}", {})
        digital |= {s["id"] for s in raw.get("sets") or []}
    set_ids: set[str] = set()
    for lang in INTERNATIONAL:
        set_ids |= {s["id"] for s in await _get(http, f"{api_url}/{lang}/sets", [])}
    cards = [
        c
        for c in await _get(http, f"{api_url}/en/cards", [])
        if c["id"].rsplit("-", 1)[0] not in digital
    ]
    english = {card_key("en", c["name"]) for c in cards}
    # The same card id names the card in every language; a name printed several ways
    # keeps its most frequent translation.
    by_id = {c["id"]: card_key("en", normalize_name(c["name"])) for c in cards}
    counts: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for lang in INTERNATIONAL[1:]:
        for c in await _get(http, f"{api_url}/{lang}/cards", []):
            if (key := by_id.get(c["id"])) and c.get("name"):
                counts[key][lang][c["name"]] += 1
    latin = {
        key: {lang: names.most_common(1)[0][0] for lang, names in by_lang.items()}
        for key, by_lang in counts.items()
    }
    return International(frozenset(set_ids - digital), frozenset(english), latin)


async def international(
    http: httpx.AsyncClient, api_url: str, digital_series: set[str]
) -> International:
    global _cached
    async with _lock:
        if _cached is None or time.monotonic() - _cached[0] > TTL:
            _cached = (time.monotonic(), await _read(http, api_url, digital_series))
        return _cached[1]


def clear() -> None:
    global _cached
    _cached = None
