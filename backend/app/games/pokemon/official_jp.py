"""The official Japanese card search (www.pokemon-card.com/card-search): pictures of
Japanese printings TCGdex has none for (its newest sets come without).

An exception to "no scraping", agreed for this game: the publisher's own open search
(`resultAPI.php`, JSON, robots.txt allows it). Requests are few and slow: one a second,
at most `TCG_POKEMON_OFFICIAL_JP_DAILY_REQUESTS` a day (counted in `api_usage`). The
list of cards (id, set, name, picture; newest first, 40 a page) is kept in a JSON file
next to the image cache, so after the first fill a run reads only the pages with new
cards. A printing gets the picture of the card of its set with its name; when a set has
several cards of one name, the card page gives each one's number (read once).
"""

import json
import logging
import re
import unicodedata
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import and_, func, select

from app.core.budget import BudgetSpent, RequestBudget
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.games.base import CardData, CatalogIndex, PrintingData, SecondaryBatch

log = logging.getLogger(__name__)

SOURCE = "pokemon-card.com"
SITE = "https://www.pokemon-card.com"
LIST_URL = f"{SITE}/card-search/resultAPI.php"
CARD_URL = f"{SITE}/card-search/details.php/card/{{id}}/regu/all"
# The list is read again from its first page after this long.
LIST_TTL = timedelta(days=1)
_NUMBER = re.compile(r"&nbsp;\s*([0-9A-Za-z-]+)\s*&nbsp;/&nbsp;")
_PICTURE = re.compile(r"/card_images/large/([^/]+)/")


def normalize(name: str) -> str:
    """Names as both sides write them: full-width letters and spaces do not count."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", name)).casefold()


@dataclass
class Wanted:
    set_ext: str
    set_code: str
    printing_ext: str
    number: str | None
    card_ext: str
    card_name: str
    name: str  # Japanese name


class Cache:
    def __init__(self, path: Path | None = None):
        self.path = path or get_settings().image_dir / "cache" / "pokemon-card-jp.json"
        data: dict[str, Any] = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
            except ValueError:
                log.warning("Unreadable %s: starting over", self.path)
        # Their card id -> [set code, name, picture path].
        self.cards: dict[str, list[str]] = data.get("cards", {})
        # Their card id -> collector number (from the card page).
        self.numbers: dict[str, str] = data.get("numbers", {})
        # Every page was read once; later runs stop at the first page with nothing new.
        self.complete: bool = data.get("complete", False)
        self.next_page: int = data.get("next_page", 1)
        self.read_at: str | None = data.get("read_at")

    def fresh(self, now: datetime) -> bool:
        return bool(
            self.complete and self.read_at and now - datetime.fromisoformat(self.read_at) < LIST_TTL
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "cards": self.cards,
            "numbers": self.numbers,
            "complete": self.complete,
            "next_page": self.next_page,
            "read_at": self.read_at,
        }
        self.path.write_text(json.dumps(data, ensure_ascii=False))


async def read_list(http: httpx.AsyncClient, budget: RequestBudget, cache: Cache) -> None:
    """New cards from the first pages, or (first fill) the next pages, while the budget
    lasts."""
    now = datetime.now(UTC)
    if cache.fresh(now):
        return
    page = 1 if cache.complete else cache.next_page
    while True:
        response = await budget.get(
            http,
            LIST_URL,
            params={"keyword": "", "regulation_sidebar_form": "all", "sm_and_keyword": "true",
                    "page": page},
        )  # fmt: skip
        data = response.json()
        new = 0
        for card in data.get("cardList") or []:
            picture = card.get("cardThumbFile") or ""
            found = _PICTURE.search(picture)
            if not found or str(card.get("cardID")) in cache.cards:
                continue
            cache.cards[str(card["cardID"])] = [
                found.group(1),
                card.get("cardNameViewText") or "",
                picture,
            ]
            new += 1
        last = page >= int(data.get("maxPage") or 0)
        if last or (cache.complete and new == 0):
            cache.complete, cache.next_page, cache.read_at = True, 1, now.isoformat()
            cache.save()
            return
        page += 1
        if not cache.complete:
            cache.next_page = page
        cache.save()


async def read_number(http: httpx.AsyncClient, budget: RequestBudget, card_id: str) -> str | None:
    response = await budget.get(http, CARD_URL.format(id=card_id))
    found = _NUMBER.search(response.text)
    return found.group(1) if found else None


async def wanted_printings() -> list[Wanted]:
    """Japanese printings without a Japanese picture, with their Japanese name."""
    from app.models import Card, CardName, CardSet, Printing

    async with get_sessionmaker()() as session:
        printing_name = (
            select(CardName.name)
            .where(CardName.printing_id == Printing.id, CardName.lang == "ja")
            .limit(1)
            .scalar_subquery()
        )
        card_name = (
            select(CardName.name)
            .where(
                and_(CardName.card_id == Card.id, CardName.printing_id.is_(None)),
                CardName.lang == "ja",
            )
            .limit(1)
            .scalar_subquery()
        )
        rows = await session.execute(
            select(
                CardSet.external_id,
                CardSet.code,
                Printing.external_id,
                Printing.collector_number,
                Card.external_id,
                Card.name,
                func.coalesce(printing_name, card_name, Card.name),
            )
            .join(Printing, Printing.set_id == CardSet.id)
            .join(Card, Printing.card_id == Card.id)
            .where(
                CardSet.game_id == "pokemon",
                CardSet.lang == "ja",
                ~Printing.image_urls.has_key("ja"),
            )
        )
        return [Wanted(*row) for row in rows]


def number_key(value: str | None) -> str:
    return (value or "").lstrip("0").casefold() or "0"


class OfficialJapaneseSource:
    id = SOURCE
    name = "pokemon-card.com"
    # Only the sets holding printings without a picture are touched.
    checks_some_sets = True

    async def fetch(
        self, http: httpx.AsyncClient, index: CatalogIndex
    ) -> AsyncIterator[SecondaryBatch]:
        from app.games.pokemon.provider import PokemonSettings

        settings = PokemonSettings()
        if not settings.official_jp:
            return
        wanted = await wanted_printings()
        if not wanted:
            return
        cache = Cache()
        budget = RequestBudget(SOURCE, "day", settings.official_jp_daily_requests, 60)
        try:
            await read_list(http, budget, cache)
        except BudgetSpent as exc:
            log.warning("%s; the rest of the list waits for the next run", exc)
        except httpx.HTTPError as exc:
            log.warning("pokemon-card.com list unavailable: %s", exc)
        theirs: dict[tuple[str, str], list[str]] = {}
        for card_id, (code, name, _) in cache.cards.items():
            theirs.setdefault((code.casefold(), normalize(name)), []).append(card_id)
        ours: dict[tuple[str, str], list[Wanted]] = {}
        for w in wanted:
            ours.setdefault((w.set_code.casefold(), normalize(w.name)), []).append(w)

        pairs: list[tuple[Wanted, str]] = []
        several: list[tuple[list[Wanted], list[str]]] = []
        for key, printings in ours.items():
            ids = theirs.get(key, [])
            if len(ids) == 1 and len(printings) == 1:
                pairs.append((printings[0], ids[0]))
            elif ids:
                several.append((printings, ids))
        # Several cards of one name: their numbers (card pages, read once) tell them
        # apart; with the budget spent, the numbers already known still count.
        reading = True
        for printings, ids in several:
            numbers = {}
            for card_id in ids:
                if card_id not in cache.numbers and reading:
                    try:
                        cache.numbers[card_id] = await read_number(http, budget, card_id) or ""
                        cache.save()
                    except BudgetSpent as exc:
                        log.warning("%s; the other card pages wait for the next run", exc)
                        reading = False
                    except httpx.HTTPError as exc:
                        log.warning("pokemon-card.com card page unavailable: %s", exc)
                        reading = False
                if card_id in cache.numbers:
                    numbers[number_key(cache.numbers[card_id])] = card_id
            pairs += [
                (w, numbers[number_key(w.number)])
                for w in printings
                if number_key(w.number) in numbers
            ]

        by_set: dict[str, SecondaryBatch] = {}
        for w, card_id in pairs:
            batch = by_set.setdefault(w.set_ext, SecondaryBatch(checked_sets=[w.set_ext]))
            batch.matched += 1
            batch.cards.append(
                CardData(
                    external_id=w.card_ext,
                    name=w.card_name,
                    partial=True,
                    printings=[
                        PrintingData(
                            external_id=w.printing_ext,
                            set_external_id=w.set_ext,
                            images={"ja": SITE + cache.cards[card_id][2]},
                        )
                    ],
                )
            )
        found = sum(len(b.cards) for b in by_set.values())
        log.info("pokemon-card.com: %s of %s Japanese pictures found", found, len(wanted))
        for batch in by_set.values():
            yield batch


source = OfficialJapaneseSource()
