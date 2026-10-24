"""The official Asian card searches, for the Asia game's languages TCGdex covers badly:

- asia.pokemon-card.com (The Pokémon Company Asia): Thai (`th`), Indonesian (`id`) and
  Traditional Chinese (`tw`, our `zh-hant`) at `/<lang>/card-search/`. Products are
  listed with their code (`expansionCodes`), each product's cards 20 a page
  (`list/?expansionCodes=<code>&pageNo=<n>`), and each card page (`detail/<id>/`) gives
  its name, number ("001/130"), Pokédex number, HP, type and illustrator.
- pokemoncard.co.kr (Pokémon Korea): the search page loads cards 30 at a time from
  `/v2/ajax2_dev2` (card id and picture). The picture path holds the product code and
  number ("wmimages/MEGA/M6a/M6a_001.png", Japanese codes), so a listed card already
  joins its set; its page (`/cards/detail/<id>`) gives the name.

An exception to "no scraping", like the Japanese search (`official_jp.py`): the
publishers' own open searches (no robots.txt rule against them), read slowly, one
request a second and at most `TCG_POKEMON_OFFICIAL_ASIA_DAILY_REQUESTS` a day per site
language. What was read is kept in `<image dir>/cache/pokemon-official-<lang>.json`:
listed cards and card pages are read once, product lists again after `LIST_TTL`, so after
the first fill (a few days) a run costs a few requests.

The cards are then handed to the catalog sync like the open datasets' (`asia.py`): a card
of a set code we have (Japanese set, or a set of another of these languages) joins the
printing of its number (language, name, picture), others are added.
"""

import asyncio
import html
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx

from app.core.budget import BudgetSpent, RequestBudget
from app.core.config import get_settings
from app.games.base import CardData, PrintingData, SetData
from app.games.pokemon import asia
from app.games.pokemon.species import derive_names, species_names
from app.games.pokemon.types import card_colors

log = logging.getLogger(__name__)

ASIA_SITE = "https://asia.pokemon-card.com"
KOREA_SITE = "https://pokemoncard.co.kr"
KOREA_IMAGES = "https://cards.image.pokemonkorea.co.kr/data/"
# Our language -> the site's path segment.
ASIA_LANGUAGES = {"th": "th", "id": "id", "zh-hant": "tw"}
LANGUAGES = (*ASIA_LANGUAGES, "ko")
# Product lists (new cards of a known product, promos) are read again after this long.
LIST_TTL = timedelta(days=14)
# Korea's search tabs: Pokémon, Trainers, Energies; and its page size.
KOREA_TABS = ("1", "2", "3")
KOREA_PAGE = 30

_ASIA_PRODUCT = re.compile(
    r'class="expansionCode"\s+value="([^"]+)"\s*>\s*<label[^>]*>([^<]*)</label>'
)
_ASIA_CARD = re.compile(r'href="/\w+/card-search/detail/(\d+)/"')
_ASIA_PAGES = re.compile(r"pageNo=(\d+)")
_ASIA_NAME = re.compile(
    r'<h1 class="pageHeader cardDetail">(?:\s*<span class="evolveMarker">[^<]*</span>)?(.*?)</h1>',
    re.S,
)
_ASIA_HP = re.compile(r'class="hitPoint">HP</span>\s*<span class="number">(\d+)</span>')
_ASIA_TYPE = re.compile(r'class="mainInfomation">.*?/energy/(\w+)\.png', re.S)
_ASIA_NUMBER = re.compile(r'class="collectorNumber">\s*([^<\s]+)\s*<')
_ASIA_ARTIST = re.compile(r'class="illustrator">.*?<a [^>]*>([^<]*)</a>', re.S)
_ASIA_DEX = re.compile(r'class="extraInformation">\s*<h3>\s*No\.\s*(\d+)')
_ASIA_SET = re.compile(
    r'class="expansionLinkColumn">.*?expansionCodes=([^"&]+)"[^>]*>([^<]*)<', re.S
)
_ASIA_IMAGE = re.compile(r'class="cardImage">\s*<img src="([^"]+)"')

_KO_NAME = re.compile(r'class="card-hp title">([^<]*)<')
_KO_NUMBER = re.compile(r'class="p_num">\s*([^<\s]+)')
_KO_HP = re.compile(r'class="hp_num">\s*HP\s*(\d+)')
_KO_TYPE = re.compile(r'class="hp_num">.*?class="type_b"[^>]*title="([^"]+)"', re.S)
_KO_ARTIST = re.compile(r'class="illustrator">[^<]*<br\s*/?>\s*([^<]*)<')
_KO_DEX = re.compile(r"<!--\s*No\.\s*(\d+)\s*-->")
_KO_SET = re.compile(r'class="search_href">([^<]*)<')
# The card's picture is the first one of the page (related cards follow).
_KO_PICTURE = re.compile(r'key=([^"&]*wmimages[^"&]*)')
# Korea's type names.
_KO_TYPES = {
    "풀": "Grass",
    "불꽃": "Fire",
    "물": "Water",
    "번개": "Lightning",
    "초": "Psychic",
    "격투": "Fighting",
    "악": "Darkness",
    "강철": "Metal",
    "페어리": "Fairy",
    "드래곤": "Dragon",
    "무색": "Colorless",
}
# Thai words before a species name, and the English form they give.
_TH_FORMS = {
    "เมก้า": "Mega {}",
    "อโลลา": "Alolan {}",
    "กาลาร์": "Galarian {}",
    "ฮิซุย": "Hisuian {}",
    "พัลเดีย": "Paldean {}",
}
# Suffixes printed after the name, kept as they are in English.
_SUFFIX = re.compile(r"\s*(ex|EX|GX|V|VMAX|VSTAR|V-UNION|BREAK|LV\.X|☆|◇)$")


def _text(value: str | None) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def _found(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return _text(match.group(1)) if match else None


@dataclass
class OfficialCard:
    """A card of one of the sites (what its page gives; `name` None: not read yet)."""

    code: str
    number: str | None
    image: str | None
    name: str | None = None
    set_name: str | None = None
    total: int | None = None
    dex: int | None = None
    hp: int | None = None
    types: list[str] = field(default_factory=list)
    artist: str | None = None


def parse_number(value: str | None) -> tuple[str | None, int | None]:
    """ "001/130" -> ("001", 130); "SV-P 012" -> ("012", None)."""
    if not value:
        return None, None
    number, _, total = value.partition("/")
    number = number.split()[-1] if number.split() else number
    return number or None, int(total) if total.isdigit() else None


def parse_asia_detail(page: str, code: str | None = None) -> OfficialCard | None:
    """A card page of asia.pokemon-card.com; None when it is not one."""
    name = _found(_ASIA_NAME, page)
    if not name:
        return None
    number, total = parse_number(_found(_ASIA_NUMBER, page))
    found_set = _ASIA_SET.search(page)
    dex = _found(_ASIA_DEX, page)
    hp = _found(_ASIA_HP, page)
    kind = _found(_ASIA_TYPE, page)
    return OfficialCard(
        code=unquote(found_set.group(1)) if found_set else code or "",
        number=number,
        image=_found(_ASIA_IMAGE, page),
        name=name,
        set_name=_text(found_set.group(2)) if found_set else None,
        total=total,
        dex=int(dex) if dex else None,
        hp=int(hp) if hp else None,
        types=[kind] if kind else [],
        artist=_found(_ASIA_ARTIST, page) or None,
    )


def korea_picture(path: str) -> tuple[str, str | None, str] | None:
    """Set code, number and picture URL from a Korean picture path
    ("wmimages/MEGA/M6a/M6a_001.png?w=400")."""
    path = unquote(path).split("?")[0]
    if "wmimages/" not in path:
        return None
    path = path[path.index("wmimages/") :]
    parts = path.split("/")
    if len(parts) < 3:
        return None
    code = parts[-2]
    stem = parts[-1].rsplit(".", 1)[0]
    prefix, _, number = stem.rpartition("_")
    # Old pictures are named otherwise ("bs1_kr_19"): no number from them.
    if prefix.casefold() != code.casefold():
        number = ""
    return code, number or None, KOREA_IMAGES + path


def parse_korea_detail(page: str) -> OfficialCard | None:
    name = _found(_KO_NAME, page)
    picture = _found(_KO_PICTURE, page)
    place = korea_picture(picture) if picture else None
    if not name or place is None:
        return None
    code, image_number, image = place
    number, total = parse_number(_found(_KO_NUMBER, page))
    dex, hp, kind = _found(_KO_DEX, page), _found(_KO_HP, page), _found(_KO_TYPE, page)
    return OfficialCard(
        code=code,
        number=image_number or number,
        image=image,
        name=name,
        set_name=_found(_KO_SET, page),
        total=total,
        dex=int(dex) if dex else None,
        hp=int(hp) if hp else None,
        types=[_KO_TYPES[kind]] if kind in _KO_TYPES else [],
        artist=_found(_KO_ARTIST, page) or None,
    )


class Cache:
    """What was read from one site language."""

    def __init__(self, lang: str, path: Path | None = None):
        self.lang = lang
        self.path = path or get_settings().image_dir / "cache" / f"pokemon-official-{lang}.json"
        data: dict[str, Any] = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
            except ValueError:
                log.warning("Unreadable %s: starting over", self.path)
        # Product code -> [name, date its list was last read in full or None].
        self.products: dict[str, list[Any]] = data.get("products", {})
        # Their card id -> [product code, number or None, picture].
        self.listed: dict[str, list[Any]] = data.get("listed", {})
        # Their card id -> card page data (OfficialCard fields).
        self.cards: dict[str, dict[str, Any]] = data.get("cards", {})
        # Korea: tabs read in full once, then from their first page.
        self.complete: list[str] = data.get("complete", [])
        self.next_page: dict[str, int] = data.get("next_page", {})
        self.read_at: str | None = data.get("read_at")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "products": self.products,
            "listed": self.listed,
            "cards": self.cards,
            "complete": self.complete,
            "next_page": self.next_page,
            "read_at": self.read_at,
        }
        self.path.write_text(json.dumps(data, ensure_ascii=False))

    def official_cards(self) -> list[OfficialCard]:
        """Every card known, read pages first (newest products first)."""
        out = []
        for card_id, (code, number, image) in self.listed.items():
            read = self.cards.get(card_id)
            if read:
                out.append(OfficialCard(**read))
            else:
                out.append(OfficialCard(code=code, number=number, image=image))
        return out


def _stale(read_at: str | None, now: datetime) -> bool:
    return not read_at or now - datetime.fromisoformat(read_at) >= LIST_TTL


async def crawl_asia(
    http: httpx.AsyncClient, budget: RequestBudget, cache: Cache, lang: str
) -> None:
    """Products, their card lists, then card pages not read yet, while the budget lasts
    (`BudgetSpent` stops it; what was read is saved)."""
    site = f"{ASIA_SITE}/{ASIA_LANGUAGES[lang]}/card-search"
    now = datetime.now(UTC)
    if _stale(cache.read_at, now):
        page = (await budget.get(http, f"{site}/")).text
        for code, name in _ASIA_PRODUCT.findall(page):
            known = cache.products.get(code)
            cache.products[code] = [_text(name), known[1] if known else None]
        cache.read_at = now.isoformat()
        cache.save()
    # The site lists the newest products first. Each product's cards are read right
    # after its list, so the first days already bring whole products.
    for code, (_, read_at) in cache.products.items():
        if _stale(read_at, now):
            page_no, pages = 1, 1
            while page_no <= pages:
                page = (
                    await budget.get(
                        http, f"{site}/list/", params={"expansionCodes": code, "pageNo": page_no}
                    )
                ).text
                pages = max([pages, *(int(n) for n in _ASIA_PAGES.findall(page))])
                for card_id in _ASIA_CARD.findall(page):
                    if card_id not in cache.listed:
                        cache.listed[card_id] = [code, None, None]
                page_no += 1
            cache.products[code][1] = now.isoformat()
            cache.save()
        await read_cards(http, budget, cache, f"{site}/detail/{{}}/", code)
    # Cards of products the site no longer lists.
    await read_cards(http, budget, cache, f"{site}/detail/{{}}/")


async def read_cards(
    http: httpx.AsyncClient,
    budget: RequestBudget,
    cache: Cache,
    url: str,
    code: str | None = None,
) -> None:
    """Card pages not read yet (of one product), `url` holding `{}` for the card id."""
    unread = [
        card_id
        for card_id, (listed_code, _, _) in cache.listed.items()
        if card_id not in cache.cards and code in (None, listed_code)
    ]
    for card_id in unread:
        page = await _page(http, budget, url.format(card_id))
        if page is None:
            del cache.listed[card_id]
            continue
        if cache.lang == "ko":
            card = parse_korea_detail(page)
        else:
            card = parse_asia_detail(page, cache.listed[card_id][0])
        if card is not None:
            cache.cards[card_id] = card.__dict__
            cache.listed[card_id] = [card.code, card.number, card.image]
            cache.save()


async def crawl_korea(http: httpx.AsyncClient, budget: RequestBudget, cache: Cache) -> None:
    """The card list (newest first: once complete, read until a page with nothing new),
    then the card pages not read yet."""
    now = datetime.now(UTC)
    if _stale(cache.read_at, now) or len(cache.complete) < len(KOREA_TABS):
        for tab in KOREA_TABS:
            done = tab in cache.complete
            page = 0 if done else cache.next_page.get(tab, 0)
            while True:
                await budget.take()
                response = await http.post(
                    f"{KOREA_SITE}/v2/ajax2_dev2",
                    files={k: (None, v) for k, v in _korea_form(tab, page).items()},
                    # Without it the site answers "접근불가" (no access).
                    headers={
                        "Referer": f"{KOREA_SITE}/cards",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                )
                response.raise_for_status()
                rows = _korea_rows(response.text)
                if not rows and page == 0:
                    # Refused or changed: tried again next run.
                    log.warning("Pokémon Korea card list (tab %s) answered no card", tab)
                    break
                new = 0
                for row in rows:
                    card_id = str(row.get("CardNum") or "")
                    place = korea_picture(str(row.get("feature_image") or ""))
                    if not card_id or place is None or card_id in cache.listed:
                        continue
                    code, number, image = place
                    cache.listed[card_id] = [code, number, image]
                    new += 1
                page += 1
                if not done:
                    cache.next_page[tab] = page
                cache.save()
                if len(rows) < KOREA_PAGE or (done and new == 0):
                    break
            if not done and cache.next_page.get(tab):
                cache.complete.append(tab)
        cache.read_at = now.isoformat()
        cache.save()
    await read_cards(http, budget, cache, f"{KOREA_SITE}/cards/detail/{{}}")


async def _page(http: httpx.AsyncClient, budget: RequestBudget, url: str) -> str | None:
    """A card page; None when the site no longer has it (listed again if it comes back)."""
    try:
        return (await budget.get(http, url)).text
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise


def _korea_form(tab: str, page: int) -> dict[str, str]:
    form = {
        "action": "get_more_cards",
        "limit": str(page),
        "GoodsName": "",
        "CardTypeNum": tab,
        "CardType": "",
        "order": "DESC",
        "orderby": "order_num",
    }
    if tab == "1":
        form |= {
            "CardMonType": "",
            "Weakness": "",
            "Resistance": "",
            "TechErg": "",
            "ability_label1": "",
            "hp": "0,380",
            "retreat": "0,5",
        }
    return form


def _korea_rows(text: str) -> list[dict[str, Any]]:
    try:
        result = json.loads(text).get("result") or []
    except (ValueError, AttributeError):
        return []
    rows = list(result.values()) if isinstance(result, dict) else result
    return [r for r in rows if isinstance(r, dict)]


def thai_english(name: str, dex: int | None) -> str | None:
    """English name of a Thai Pokémon card from its Pokédex number, when the name is only
    the species (with a known form word or suffix): no Thai species names are known."""
    english = (species_names().get(dex) or {}).get("en") if dex else None
    if not english:
        return None
    # Regional forms are also written "<อโลลา> นัชชี".
    rest, form = re.sub(r"[<>]", "", name).strip(), "{}"
    for word, english_form in _TH_FORMS.items():
        if rest.startswith(word):
            rest, form = rest[len(word) :].strip(), english_form
            break
    suffix = _SUFFIX.search(rest)
    if suffix:
        rest = rest[: suffix.start()].strip()
    # Anything Latin left ("X" of Mega Charizard X) or several words: not only the species.
    if not rest or re.search(r"[A-Za-z0-9\s<>]", rest):
        return None
    english = form.format(english)
    return f"{english} {suffix.group(1)}" if suffix else english


def to_card(card: OfficialCard, lang: str, set_id: str) -> CardData:
    """Card data of an official card (read or only listed: then name "")."""
    number = card.number or ""
    category = "Pokemon" if card.hp else None
    printing = PrintingData(
        external_id=number,
        set_external_id=set_id,
        collector_number=number,
        artist=asia.artists([card.artist] if card.artist else None),
        finishes=["normal"],
        languages=[lang],
        images={lang: card.image} if card.image else {},
    )
    name = card.name or ""
    names = {lang: name} if name else {}
    attributes: dict[str, Any] = {}
    if category:
        attributes["category"] = category
        attributes["hp"] = card.hp
    if card.dex:
        attributes["dexId"] = [card.dex]
    if name and category == "Pokemon":
        dex = [card.dex] if card.dex else []
        if lang == "th":
            english = thai_english(name, card.dex)
            if english:
                names["en"] = english
        elif lang == "id":
            # Indonesian cards print the English species names ("Alolan Exeggutor").
            species = (species_names().get(card.dex) or {}).get("en") if card.dex else None
            if derive_names(name, "en", dex) or (species and species in name):
                names["en"] = name
        else:
            names = derive_names(name, lang, dex) | names
    return CardData(
        external_id=f"{lang}:{name.casefold()}",
        name=name,
        colors=card_colors(card.types, category),
        attributes=attributes,
        printings=[printing],
        names=names,
    )


def asian_sets(cache: Cache, lang: str) -> list[asia.AsianSet]:
    """The site's cards as sets for `join_asian_set`, newest products first."""
    sets: dict[str, asia.AsianSet] = {}
    for card in cache.official_cards():
        if not card.code or not card.number:
            continue
        key = card.code.casefold()
        if key not in sets:
            product = cache.products.get(card.code)
            sets[key] = asia.AsianSet(
                card.code,
                SetData(
                    external_id=card.code,
                    code=card.code,
                    name=(product[0] if product else None) or card.set_name or card.code,
                    lang=lang,
                    total=card.total,
                ),
            )
        found = sets[key]
        if found.data.total is None and card.total:
            found.data.total = card.total
        found.cards.append(to_card(card, lang, card.code))
    return list(sets.values())


async def read_site(http: httpx.AsyncClient, lang: str, daily: int) -> list[asia.AsianSet]:
    """Read more of one site language (within its daily budget), then every card known."""
    cache = Cache(lang)
    budget = RequestBudget(f"pokemon-official-{lang}", "day", daily, 60)
    try:
        if lang == "ko":
            await crawl_korea(http, budget, cache)
        else:
            await crawl_asia(http, budget, cache, lang)
    except BudgetSpent as exc:
        log.info("%s; the rest waits for the next run", exc)
    except httpx.HTTPError as exc:
        log.warning("Official Pokémon card search (%s) unavailable: %s", lang, exc)
    cache.save()
    log.info(
        "Official Pokémon card search (%s): %s cards listed, %s read (%s requests)",
        lang,
        len(cache.listed),
        len(cache.cards),
        budget.used,
    )
    return asian_sets(cache, lang)


async def read_sites(
    http: httpx.AsyncClient, languages: list[str], daily: int
) -> dict[str, list[asia.AsianSet]]:
    """Each site language read in turn on asia.pokemon-card.com (one site), Korea's at the
    same time."""

    async def asia_site() -> dict[str, list[asia.AsianSet]]:
        return {lang: await read_site(http, lang, daily) for lang in languages if lang != "ko"}

    async def korea_site() -> dict[str, list[asia.AsianSet]]:
        return {"ko": await read_site(http, "ko", daily)} if "ko" in languages else {}

    found_asia, found_korea = await asyncio.gather(asia_site(), korea_site())
    return found_asia | found_korea
