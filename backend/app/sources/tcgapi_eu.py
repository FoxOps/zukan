"""TCG API (https://tcg-api.eu): English card data of Pokémon (pokemontcg.io shape, newest
sets included), Magic (MTGJSON shape), Lorcana and One Piece. No prices.

Key `TCG_APITOKEN_GAMES_TCGAPIEU` (header `X-API-Key`), skipped without one. Limits:
10 000 requests a day, 100 a minute, 100 cards a page; this source keeps
`TCG_TCGAPI_EU_DAILY_REQUESTS` (9000) and 90 a minute. It fills pictures, rarities and
artists of the sets holding such gaps.
"""

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx

from app.core.budget import BudgetSpent, RequestBudget
from app.core.config import api_token, get_settings
from app.games.base import CatalogIndex, SecondaryBatch
from app.sources.base import (
    ARTIST,
    IMAGE,
    RARITY,
    BoundSource,
    ExternalPrinting,
    ExternalSet,
    check_set,
    game_key,
    match_sets,
    sets_with_gaps,
    stored_by_set,
)

log = logging.getLogger(__name__)

BASE_URL = "https://api.tcg-api.eu/api/v1/tcg"
PAGE_SIZE = 100
# Their name of each game we have; they also cover "lorcana" and "optcg" (One Piece).
GAMES = {"pokemon": "pokemon", "mtg": "magic"}
# What this source can fill.
FILLS = {IMAGE, RARITY, ARTIST}


def token() -> str | None:
    return api_token("GAMES", "TCGAPIEU")


def _released(value: str | None):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date() if value else None


def parse_set(raw: dict[str, Any]) -> ExternalSet:
    codes = [c for c in (raw.get("code"), raw.get("id"), raw.get("ptcgo_code")) if c]
    return ExternalSet(
        key=raw["id"],
        name=raw["name"],
        codes=codes,
        release_date=_released(raw.get("release_date")),
    )


def parse_card(raw: dict[str, Any]) -> ExternalPrinting:
    image = raw.get("large_image_url") or raw.get("large_image_cdn_url") or raw.get("image_url")
    return ExternalPrinting(
        number=raw.get("number"),
        name=raw.get("face_name") or raw["name"],
        rarity=raw.get("rarity"),
        artist=raw.get("artist"),
        image=image if image and "placeholder" not in image else None,
    )


class TcgApiEuSource:
    id = "tcgapi_eu"
    name = "TCG API (tcg-api.eu)"
    order = 20
    games = GAMES

    def for_game(self, game_id: str) -> BoundSource | None:
        if game_key(self, game_id) is None or not token():
            return None
        return BoundSource(self.id, self.name, game_id, self.run)

    async def _pages(
        self, http: httpx.AsyncClient, budget: RequestBudget, path: str, key: str, **params: Any
    ) -> AsyncIterator[list[dict[str, Any]]]:
        page = 1
        while True:
            response = await budget.get(
                http,
                f"{BASE_URL}/{path}",
                params={**params, "page": page, "limit": PAGE_SIZE},
                headers={"X-API-Key": token() or ""},
            )
            data = response.json()["data"]
            yield data[key]
            if not data.get("pagination", {}).get("hasNext"):
                return
            page += 1

    async def run(
        self, http: httpx.AsyncClient, index: CatalogIndex, game_id: str
    ) -> AsyncIterator[SecondaryBatch]:
        gaps = sets_with_gaps(index, FILLS)
        if not gaps:
            return
        name = game_key(self, game_id)
        budget = RequestBudget(self.id, "day", get_settings().tcgapi_eu_daily_requests, 90)
        try:
            theirs = [
                parse_set(raw)
                async for page in self._pages(http, budget, f"{name}/sets", "sets")
                for raw in page
            ]
            matches = match_sets(index.sets, theirs, game_id)
            stored = stored_by_set(index)
            # Sets with the most gaps first, in case the quota runs out.
            wanted = sorted(
                ((key, ext) for key, ext in matches.items() if ext in gaps),
                key=lambda pair: -gaps[pair[1]],
            )
            log.info("tcg-api.eu %s: %s sets with gaps matched", game_id, len(wanted))
            for key, set_ext in wanted:
                cards = [
                    parse_card(raw)
                    async for page in self._pages(http, budget, f"{name}/cards", "cards", set=key)
                    for raw in page
                ]
                yield check_set(game_id, self.id, stored[set_ext], cards)
        except BudgetSpent as exc:
            log.warning("%s; the rest waits for the next run", exc)


source = TcgApiEuSource()
