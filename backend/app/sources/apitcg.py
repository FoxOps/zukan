"""API TCG (https://apitcg.com): TCGplayer-based card data (ids, pictures, artists,
rarities, rules text) of many games.

Key `TCG_APITOKEN_GAMES_APITCG` (header `x-api-key`), skipped without one. Free tier:
1000 requests a month (100 cards a page), so it runs last, after every other source, and
keeps to `TCG_APITCG_MONTHLY_REQUESTS` (900): only sets still holding gaps, the most
incomplete first.
"""

import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx

from app.core.budget import BudgetSpent, RequestBudget
from app.core.config import api_token, get_settings
from app.core.text import plain_text
from app.games.base import CatalogIndex, SecondaryBatch
from app.sources.base import (
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

BASE_URL = "https://api.apitcg.com/api"
PAGE_SIZE = 100
# Their slug of each game we have.
GAMES = {"mtg": "magic", "pokemon": "pokemon", "riftbound": "riftbound"}
# Every game they have (for future games: map our id to one of these in GAMES, or set
# the provider's `source_keys`).
SLUGS = (
    "cardfight-vanguard",
    "digimon",
    "dragon-ball-super-fusion-world",
    "dragon-ball-super-masters",
    "flesh-and-blood",
    "gundam",
    "hololive",
    "lorcana",
    "magic",
    "mitos-y-leyendas",
    "one-piece",
    "pokemon",
    "riftbound",
    "star-wars-unlimited",
    "union-arena",
    "yugioh",
)


def token() -> str | None:
    return api_token("GAMES", "APITCG")


def _released(value: str | None):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date() if value else None


def parse_set(raw: dict[str, Any]) -> ExternalSet:
    return ExternalSet(
        key=raw["_id"],
        name=raw["name"],
        codes=[raw["code"]] if raw.get("code") else [],
        release_date=_released(raw.get("release_date")),
    )


def parse_product(raw: dict[str, Any]) -> ExternalPrinting:
    attributes = raw.get("attributes") or {}
    tcgplayer = (raw.get("markets") or {}).get("tcgplayer") or {}
    images = raw.get("images") or [{}]
    return ExternalPrinting(
        number=attributes.get("Number") or raw.get("code"),
        name=raw["name"],
        rarity=attributes.get("Rarity"),
        artist=attributes.get("Artist"),
        image=images[0].get("large") if images else None,
        tcgplayer_id=str(tcgplayer["id"]) if tcgplayer.get("id") else None,
        text=plain_text(attributes.get("Description") or attributes.get("OracleText")),
        versions=[
            v["subTypeName"] for v in tcgplayer.get("printings") or [] if v.get("subTypeName")
        ],
    )


class ApiTcgSource:
    id = "apitcg"
    name = "API TCG (apitcg.com)"
    order = 30
    games = GAMES

    def for_game(self, game_id: str) -> BoundSource | None:
        if game_key(self, game_id) is None or not token():
            return None
        return BoundSource(self.id, self.name, game_id, self.run)

    async def _pages(
        self, http: httpx.AsyncClient, budget: RequestBudget, url: str, **params: Any
    ) -> AsyncIterator[list[dict[str, Any]]]:
        page, seen = 1, 0
        while True:
            response = await budget.get(
                http,
                url,
                params={**params, "page": page, "limit": PAGE_SIZE},
                headers={"x-api-key": token() or ""},
            )
            body = response.json()
            items = body.get("data") or []
            seen += len(items)
            yield items
            if not items or seen >= body.get("total", 0):
                return
            page += 1

    async def run(
        self, http: httpx.AsyncClient, index: CatalogIndex, game_id: str
    ) -> AsyncIterator[SecondaryBatch]:
        gaps = sets_with_gaps(index)
        if not gaps:
            return
        slug = game_key(self, game_id)
        budget = RequestBudget(self.id, "month", get_settings().apitcg_monthly_requests, 60)
        try:
            theirs = [
                parse_set(raw)
                async for page in self._pages(http, budget, f"{BASE_URL}/{slug}/sets")
                for raw in page
            ]
            matches = match_sets(index.sets, theirs, game_id)
            stored = stored_by_set(index)
            wanted = sorted(
                ((key, ext) for key, ext in matches.items() if ext in gaps),
                key=lambda pair: -gaps[pair[1]],
            )
            log.info("apitcg %s: %s sets with gaps matched", game_id, len(wanted))
            for key, set_ext in wanted:
                cards = [
                    parse_product(raw)
                    async for page in self._pages(
                        http, budget, f"{BASE_URL}/products", tcg=slug, set=key, type="card"
                    )
                    for raw in page
                ]
                yield check_set(game_id, self.id, stored[set_ext], cards)
        except BudgetSpent as exc:
            log.warning("%s; the rest waits for next month", exc)


source = ApiTcgSource()
