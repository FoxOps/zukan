"""Konami's official card database (db.yugioh-card.com): Japanese and Korean names and
printings of cards newer than YGOJSON's last update.

An exception to "no scraping", agreed for this game: the card pages are the publisher's
own data and the only source for recent OCG printings. Requests are few and slow: only
cards missing a name, at most `TCG_YUGIOH_KONAMI_DAILY_REQUESTS` a day (counted in
`api_usage`), one a second. Answers are kept in a JSON file next to the image cache so a
card is read once; pages without the card are asked again after 30 days.
"""

import html
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.budget import BudgetSpent, RequestBudget
from app.core.config import get_settings
from app.core.progress import progress

log = logging.getLogger(__name__)

URL = "https://www.db.yugioh-card.com/yugiohdb/card_search.action"
SOURCE = "konami"
LOCALES = {"ja": "ja", "ko": "ko"}
RETRY_AFTER = timedelta(days=30)
# Network errors in a row after which the site is taken as unreachable for this run.
MAX_FAILURES = 5

_NAME = re.compile(r'id="cardname"[^>]*>\s*<h1>(.*?)</h1>', re.S)
_ROW = re.compile(r'<div class="t_row[^"]*">(.*?)<!-- \.icon -->', re.S)
_TIME = re.compile(r'<div class="time">\s*([0-9-]+)\s*</div>')
_NUMBER = re.compile(r'<div class="card_number">\s*([^<\s]+)\s*</div>')
_PACK = re.compile(r'<div class="pack_name[^"]*"[^>]*>\s*(.*?)\s*</div>', re.S)
_RARITY = re.compile(r'<div class="lr_icon[^"]*"[^>]*>\s*<p>([^<]+)</p>')
_TAG = re.compile(r"<[^>]+>")


@dataclass
class Pack:
    number: str  # "YAC1-JP071"
    name: str
    released: str | None
    rarity: str | None  # Konami short code: "UR", "SE"


@dataclass
class Page:
    name: str | None
    packs: list[Pack] = field(default_factory=list)
    fetched_at: str = ""


def parse(text: str) -> Page:
    """Name (Japanese or Korean) and printings of a card page."""
    found = _NAME.search(text)
    name = None
    if found:
        inner = re.sub(r'<span class="ruby">.*?</span>', "", found.group(1), flags=re.S)
        inner = re.sub(r"<span>.*?</span>", "", inner, flags=re.S)
        name = html.unescape(_TAG.sub("", inner)).strip() or None
    packs = []
    for row in _ROW.findall(text):
        number = _NUMBER.search(row)
        if not number:
            continue
        pack = _PACK.search(row)
        released = _TIME.search(row)
        rarity = _RARITY.search(row)
        packs.append(
            Pack(
                number=number.group(1).strip(),
                name=html.unescape(_TAG.sub("", pack.group(1))).strip() if pack else "",
                released=released.group(1) if released else None,
                rarity=rarity.group(1).strip() if rarity else None,
            )
        )
    return Page(name=name, packs=packs)


class Cache:
    """Pages read so far, by Konami card id and locale."""

    def __init__(self, path: Path | None = None):
        self.path = path or get_settings().image_dir / "cache" / "yugioh-konami.json"
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError):
            raw = {}
        self.pages: dict[str, dict[str, Page]] = {
            cid: {
                lang: Page(
                    p.get("name"), [Pack(**k) for k in p.get("packs", [])], p.get("fetched_at", "")
                )
                for lang, p in by_lang.items()
            }
            for cid, by_lang in raw.items()
        }

    def get(self, cid: int, lang: str) -> Page | None:
        return self.pages.get(str(cid), {}).get(lang)

    def wanted(self, cid: int, lang: str, now: datetime) -> bool:
        page = self.get(cid, lang)
        if page is None:
            return True
        if page.name:
            return False
        try:
            fetched = datetime.fromisoformat(page.fetched_at)
        except ValueError:
            return True
        return now - fetched > RETRY_AFTER

    def put(self, cid: int, lang: str, page: Page) -> None:
        self.pages.setdefault(str(cid), {})[lang] = page

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            cid: {lang: asdict(page) for lang, page in by_lang.items()}
            for cid, by_lang in self.pages.items()
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False))
        tmp.replace(self.path)


async def fill(
    http: httpx.AsyncClient, cache: Cache, wanted: list[tuple[int, str]], daily: int
) -> int:
    """Read the pages of `wanted` (Konami id, locale) not in `cache`, newest cards first
    as given, within the day's request budget. Returns the number of pages read."""
    now = datetime.now(UTC)
    todo = [(cid, lang) for cid, lang in wanted if cache.wanted(cid, lang, now)]
    if not todo or daily <= 0:
        return 0
    budget = RequestBudget(SOURCE, "day", daily, per_minute=60)
    read = failures = 0
    try:
        for cid, lang in todo:
            await budget.take()
            try:
                response = await http.get(
                    URL, params={"ope": "2", "cid": str(cid), "request_locale": lang}, timeout=30
                )
                response.raise_for_status()
            except httpx.TransportError as exc:
                # Timeouts never reach the response hook: report progress here, and do not
                # charge the day's budget for a request the site never answered.
                await budget.refund()
                await progress()
                failures += 1
                log.warning("Konami database: card %s (%s) not read: %r", cid, lang, exc)
                if failures >= MAX_FAILURES:
                    log.warning(
                        "Konami database unreachable (%s network errors in a row), "
                        "%s pages left for the next run",
                        failures,
                        len(todo) - read,
                    )
                    break
                continue
            except httpx.HTTPError as exc:
                log.warning("Konami database: card %s (%s) not read: %s", cid, lang, exc)
                continue
            failures = 0
            page = parse(response.text)
            page.fetched_at = now.isoformat()
            cache.put(cid, lang, page)
            read += 1
    except BudgetSpent:
        log.info("Konami database: daily budget used, %s pages left", len(todo) - read)
    finally:
        if read:
            cache.save()
    return read
