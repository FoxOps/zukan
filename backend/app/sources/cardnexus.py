"""CardNexus (https://docs.cardnexus.com): a marketplace whose public API gives, per game,
three daily files (gzip, one JSON record a line): the catalog, its expansions and current
prices (Cardmarket EUR, TCGplayer USD and CardNexus' own listings, per finish).

Key `TCG_APITOKEN_PRICES_CARDNEXUS` (bearer token), skipped without one. One API request
per game and run (60 a minute allowed; this source keeps 50 and
`TCG_CARDNEXUS_DAILY_REQUESTS`); the files themselves are presigned downloads, kept
next to the image cache and downloaded again only when their checksum changes.

As a gap source (catalog job) it fills English pictures, rarities and market ids
(Cardmarket, TCGplayer, CardNexus) of stored printings, and adds the printings a stored
set lacks when the set's printings are keyed on their collector number (a primary sync
finding them later updates the same rows). Its prices are the `cardnexus` price source
(`app.prices.cardnexus`).
"""

import gzip
import hashlib
import io
import json
import logging
import re
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

from app.core.budget import BudgetSpent, RequestBudget
from app.core.config import api_token, get_settings
from app.games.base import (
    CardData,
    CatalogIndex,
    PriceQuote,
    PrintingData,
    SecondaryBatch,
    StoredPrinting,
    registry,
)
from app.prices.base import MarketTarget
from app.sources.base import (
    ARTIST,
    IMAGE,
    RARITY,
    TCGPLAYER,
    BoundSource,
    ExternalPrinting,
    ExternalSet,
    fill,
    game_key,
    match_sets,
    number_key,
    pair,
    remember,
    same_name,
    sets_with_gaps,
    stored_by_set,
    unchecked,
)

log = logging.getLogger(__name__)

SOURCE = "cardnexus"
BASE_URL = "https://public-api.cardnexus.com/v1"
SITE_URL = "https://cardnexus.com"
# Their games for each of ours (Japanese Pokémon cards are a game of their own there).
GAMES: dict[str, list[str]] = {
    "mtg": ["mtg"],
    "pokemon": ["pokemon", "pokemon-japan"],
    "yugioh": ["ygo"],
    "sorcery": ["sorcery"],
    "lorcana": ["lorcana"],
    "riftbound": ["riftbound"],
}
FILLS = {IMAGE, RARITY, ARTIST, TCGPLAYER}
# The largest file (Magic's catalog) is some 60 MB.
MAX_FEED_BYTES = 400 * 1024 * 1024
# Their finish names, as our finish codes in order of preference (the game's first).
FINISHES: dict[str, tuple[str, ...]] = {
    "standard": ("normal", "nonfoil", "standard", "unlimited"),
    "foil": ("foil", "holo"),
    "reverse holo": ("reverse",),
    "rainbow": ("rainbow",),
    "etched": ("etched",),
    "1st edition": ("first_edition", "first"),
}
# Share of a set's stored printings found in theirs for it to add the ones we lack.
SAME_SET_SHARE = 0.8
# Prices older than this are a market without recent sales: left out.
MAX_PRICE_AGE = timedelta(days=30)
# Languages of their site.
SITE_LANGUAGES = {"en", "fr", "de", "es", "it"}


def token() -> str | None:
    return api_token("PRICES", "CARDNEXUS")


def their_games(game_id: str) -> list[str]:
    key = game_key(source, game_id)
    if key is None:
        return []
    return [key] if isinstance(key, str) else list(key)


def finish_code(game_id: str, theirs: str) -> str | None:
    provider = registry().get(game_id)
    have = [f.code for f in getattr(provider, "finishes", [])]
    return next((c for c in FINISHES.get(theirs.casefold(), ()) if c in have), None)


def market_path(raw: dict[str, Any], cn_game: str) -> str:
    """Their product page path, stored as the printing's market id: "pokemon/
    me02-phantasmal-flames/card/mega-diancie-ex-154426" (the product id last)."""
    return f"{cn_game}/{raw.get('expansionSlug')}/card/{raw.get('nameSlug')}-{raw['id']}"


def product_id(market_id: Any) -> int | None:
    found = re.search(r"(\d+)$", str(market_id or ""))
    return int(found.group(1)) if found else None


def link(market_id: Any, lang: str) -> str | None:
    if not market_id or "/" not in str(market_id):
        return None
    return f"{SITE_URL}/{lang if lang in SITE_LANGUAGES else 'en'}/explore/{market_id}"


class Feeds:
    """Their daily files of one game, downloaded when changed."""

    def __init__(self, http: httpx.AsyncClient, budget: RequestBudget, folder: Path | None = None):
        self.http = http
        self.budget = budget
        self.folder = folder or get_settings().image_dir / "cache" / "cardnexus"
        self.links: dict[str, dict[str, Any]] = {}

    async def path(self, cn_game: str, kind: str) -> Path | None:
        """The file of `kind` (catalog, expansions, prices), None when not generated."""
        if cn_game not in self.links:
            response = await self.budget.get(
                self.http,
                f"{BASE_URL}/feeds/{cn_game}",
                headers={"Authorization": f"Bearer {token() or ''}"},
            )
            self.links[cn_game] = response.json()
        meta = self.links[cn_game].get(kind)
        if not meta or not meta.get("url"):
            return None
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f"{cn_game}-{kind}.ndjson.gz"
        stamp = path.with_suffix(".sha256")
        checksum = meta.get("checksum") or ""
        if path.exists() and stamp.exists() and stamp.read_text().strip() == checksum:
            return path
        body = await self._download(meta["url"])
        if checksum and _content_hash(body) != checksum:
            raise httpx.HTTPError(f"CardNexus {cn_game} {kind} file does not match its checksum")
        path.write_bytes(body)
        stamp.write_text(checksum)
        return path

    async def _download(self, url: str) -> bytes:
        chunks: list[bytes] = []
        size = 0
        # A presigned link: no API key, not counted in the budget.
        async with self.http.stream("GET", url, timeout=300) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_FEED_BYTES:
                    raise httpx.HTTPError(f"CardNexus file over {MAX_FEED_BYTES} bytes: {url}")
                chunks.append(chunk)
        return b"".join(chunks)

    async def records(self, cn_game: str, kind: str) -> Iterator[dict[str, Any]]:
        path = await self.path(cn_game, kind)
        return _lines(path) if path else iter(())


def _content_hash(body: bytes) -> str:
    """Their checksum: SHA-256 of the uncompressed file (read in chunks: some are big)."""
    digest = hashlib.sha256()
    with gzip.GzipFile(fileobj=io.BytesIO(body)) as file:
        while chunk := file.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _lines(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                yield json.loads(line)


def budget() -> RequestBudget:
    return RequestBudget(SOURCE, "day", get_settings().cardnexus_daily_requests, 50)


def _date(value: str | None) -> date | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date() if value else None
    except ValueError:
        return None


_PREFIX = re.compile(r"^([A-Za-z0-9.]+):\s+(.+)$")


def parse_expansion(raw: dict[str, Any]) -> ExternalSet:
    """Pokémon expansions are named "ME01: Mega Evolution": the code before the colon."""
    name = raw.get("name") or ""
    codes = [raw.get("code"), (raw.get("attributes") or {}).get("setId")]
    if found := _PREFIX.match(name):
        codes.insert(0, found.group(1))
        name = found.group(2)
    return ExternalSet(
        key=raw["id"],
        name=name,
        codes=[c for c in codes if c],
        release_date=_date(raw.get("releaseDate")),
    )


def market_ids(raw: dict[str, Any], cn_game: str) -> dict[str, str]:
    ids = {SOURCE: market_path(raw, cn_game)}
    for market in ("cardmarket", "tcgplayer"):
        found = (raw.get("externalIds") or {}).get(market)
        if isinstance(found, list) and found and found[0].get("id"):
            ids[market] = str(found[0]["id"])
    return ids


@dataclass
class Product:
    raw: dict[str, Any]
    cn_game: str

    def external(self) -> ExternalPrinting:
        raw = self.raw
        ids = market_ids(raw, self.cn_game)
        rarity = raw.get("rarity")
        return ExternalPrinting(
            number=raw.get("printNumber"),
            name=raw.get("name") or "",
            # "DOUBLE_RARE" -> "Double Rare"; "NONE": none.
            rarity=rarity.replace("_", " ").title() if rarity and "_" in rarity else rarity,
            artist=(raw.get("attributes") or {}).get("artist"),
            image=raw.get("imageUrl") if "en" in (raw.get("languages") or ["en"]) else None,
            tcgplayer_id=ids.get("tcgplayer"),
            versions=list(raw.get("finishes") or []),
        )


async def _products(
    feeds: Feeds, cn_game: str
) -> tuple[list[ExternalSet], dict[Any, list[Product]]]:
    sets = [parse_expansion(raw) for raw in await feeds.records(cn_game, "expansions")]
    by_set: dict[Any, list[Product]] = {}
    for raw in await feeds.records(cn_game, "catalog"):
        if raw.get("productType") == "card":
            # Only what is used: some catalogs carry long translated texts.
            slim = {k: raw.get(k) for k in _KEPT}
            slim["attributes"] = {"artist": (raw.get("attributes") or {}).get("artist")}
            by_set.setdefault(raw.get("expansionId"), []).append(Product(slim, cn_game))
    return sets, by_set


_KEPT = (
    "id",
    "name",
    "nameSlug",
    "expansionSlug",
    "printNumber",
    "rarity",
    "finishes",
    "languages",
    "imageUrl",
    "externalIds",
)
# Their language codes that differ from ours.
_LANGUAGES = {"pt-br": "pt", "zh-cn": "zh-hans", "zh-tw": "zh-hant"}


def _languages(game_id: str, theirs: list[str]) -> list[str]:
    have = set(getattr(registry().get(game_id), "languages", []) or [])
    out = [_LANGUAGES.get(lang.casefold(), lang.casefold()) for lang in theirs]
    return list(dict.fromkeys(lang for lang in out if not have or lang in have))


def _like(stored: list[StoredPrinting], number: str) -> str:
    """Their number written like the set's stored ones: zero padded ("041") or not."""
    if not number.isdigit():
        return number
    padded = [p.collector_number for p in stored if (p.collector_number or "").isdigit()]
    width = max((len(n) for n in padded if n.startswith("0")), default=0)
    return number.lstrip("0").zfill(width) if width else (number.lstrip("0") or "0")


def _numbered(stored: list[StoredPrinting]) -> bool:
    """The set's printings are keyed on their collector number ("022"): a printing we add
    gets the key the primary source would give it."""
    return bool(stored) and all(p.external_id == p.collector_number for p in stored)


def check_products(
    game_id: str,
    stored: list[StoredPrinting],
    products: list[Product],
    cards_by_name: dict[str, tuple[str, str]],
) -> SecondaryBatch:
    """Fill gaps of `stored` from `products` (one set), store their market ids, and add
    the products the set lacks (by number, of a card we have under that name)."""
    batch = SecondaryBatch(checked_sets=sorted({p.set_external_id for p in stored}))
    external = [(p, p.external()) for p in products]
    by_ext = {id(ext): product for product, ext in external}
    paired = pair(stored, [ext for _, ext in external])
    seen_numbers = {number_key(p.collector_number or p.external_id) for p in stored}
    for printing, ext in paired:
        batch.matched += 1
        product = by_ext[id(ext)]
        card, found = fill(game_id, SOURCE, printing, ext)
        batch.discrepancies += found
        ids = {
            k: v
            for k, v in market_ids(product.raw, product.cn_game).items()
            if not printing.market_ids.get(k)
        }
        if ids:
            if card is None:
                card = CardData(
                    external_id=printing.card_external_id,
                    name=printing.card_name,
                    partial=True,
                    printings=[
                        PrintingData(
                            external_id=printing.external_id,
                            set_external_id=printing.set_external_id,
                        )
                    ],
                )
            data = card.printings[0]
            data.attributes["market_ids"] = {**data.attributes.get("market_ids", {}), **ids}
        if card is not None:
            batch.cards.append(card)
    # Sets matched by a code two sets share ("SV": Supreme Victors and the Scarlet &
    # Violet promos) pair few printings: only a set clearly the same one gets new ones.
    if not _numbered(stored) or len(paired) < SAME_SET_SHARE * len(stored):
        return batch
    set_ext = stored[0].set_external_id
    for product, ext in external:
        if not ext.number or number_key(ext.number) in seen_numbers:
            continue
        number = _like(stored, ext.number)
        owner = cards_by_name.get(ext.name.casefold())
        if owner is None:
            continue
        card_ext, card_name = owner
        if not same_name(card_name, ext.name):
            continue
        seen_numbers.add(number_key(number))
        finishes = [c for f in ext.versions if (c := finish_code(game_id, f))]
        languages = _languages(game_id, product.raw.get("languages") or [])
        batch.cards.append(
            CardData(
                external_id=card_ext,
                name=card_name,
                partial=True,
                printings=[
                    PrintingData(
                        external_id=number,
                        set_external_id=set_ext,
                        collector_number=number,
                        rarity=ext.rarity if ext.rarity and ext.rarity != "NONE" else None,
                        artist=ext.artist,
                        finishes=list(dict.fromkeys(finishes)),
                        languages=languages,
                        images={"en": ext.image} if ext.image else {},
                        attributes={
                            "market_ids": market_ids(product.raw, product.cn_game),
                            "added_by": SOURCE,
                        },
                        partial=False,
                    )
                ],
            )
        )
    return batch


class CardNexusSource:
    id = SOURCE
    name = "CardNexus"
    # After the free sources, before the ones with small quotas.
    order = 15
    games = GAMES

    def for_game(self, game_id: str) -> BoundSource | None:
        if not their_games(game_id) or not token():
            return None
        return BoundSource(self.id, self.name, game_id, self.run)

    async def run(
        self, http: httpx.AsyncClient, index: CatalogIndex, game_id: str
    ) -> AsyncIterator[SecondaryBatch]:
        stored = stored_by_set(index)
        # Every set: market ids and missing printings are gaps too, not only pictures.
        gaps = {s: len(p) + sets_with_gaps(index, FILLS).get(s, 0) for s, p in stored.items()}
        gaps = await unchecked(self.id, game_id, gaps)
        if not gaps:
            return
        cards_by_name: dict[str, tuple[str, str]] = {}
        for printing in index.printings.values():
            cards_by_name.setdefault(
                printing.card_name.casefold(), (printing.card_external_id, printing.card_name)
            )
        feeds = Feeds(http, budget())
        try:
            # Their first game holds the international sets (Japanese Pokémon cards are
            # another game there, only used for prices).
            for cn_game in their_games(game_id)[:1]:
                theirs, products = await _products(feeds, cn_game)
                matches = match_sets(index.sets, theirs, game_id)
                log.info("CardNexus %s (%s): %s sets matched", game_id, cn_game, len(matches))
                for key, set_ext in matches.items():
                    if set_ext not in gaps or key not in products:
                        continue
                    yield check_products(game_id, stored[set_ext], products[key], cards_by_name)
                    await remember(self.id, game_id, set_ext, gaps[set_ext])
        except BudgetSpent as exc:
            log.warning("%s; the rest waits for the next run", exc)


def _money(value: Any) -> Decimal | None:
    if isinstance(value, dict):
        value = value.get("amount")
    if value is None:
        return None
    try:
        found = Decimal(str(value))
    except InvalidOperation:
        return None
    return found if found > 0 else None


def quotes_for(
    game_id: str, target: MarketTarget, prices: dict[str, Any], today: date
) -> list[PriceQuote]:
    """Quotes of one target from its product's `pricesByFinish`: CardNexus' lowest
    listing, and Cardmarket / TCGplayer where no other source priced it today."""
    out = []
    for theirs, markets in prices.items():
        finish = finish_code(game_id, theirs)
        if finish is None or finish not in target.finishes:
            continue
        nexus = markets.get("cardnexus") or {}
        if low := _money(nexus.get("low")):
            out.append(
                PriceQuote(
                    target.set_external_id,
                    target.printing_external_id,
                    finish,
                    trend=low,
                    low=low,
                    currency="EUR",
                    source=SOURCE,
                )
            )
        for market, currency in (("cardmarket", "EUR"), ("tcgplayer", "USD")):
            price = markets.get(market)
            if not price or market in target.quoted:
                continue
            day = _date(price.get("date"))
            if day is None or today - day > MAX_PRICE_AGE:
                continue
            trend = _money(price.get("marketValue")) or _money(price.get("mid"))
            if trend is None:
                continue
            out.append(
                PriceQuote(
                    target.set_external_id,
                    target.printing_external_id,
                    finish,
                    trend=trend,
                    low=_money(price.get("low")),
                    avg=_money(price.get("mid")),
                    currency=price.get("currency") or currency,
                    source=market,
                )
            )
    return out


async def fetch_prices(
    http: httpx.AsyncClient, game_id: str, targets: list[MarketTarget]
) -> AsyncIterator[list[PriceQuote]]:
    """Quotes of the targets CardNexus knows: by their CardNexus product id, else their
    Cardmarket or TCGplayer one."""
    if not token():
        return
    by_market: dict[str, dict[str, MarketTarget]] = {SOURCE: {}, "cardmarket": {}, "tcgplayer": {}}
    for target in targets:
        if pid := product_id(target.market_ids.get(SOURCE)):
            by_market[SOURCE][str(pid)] = target
        for market in ("cardmarket", "tcgplayer"):
            if found := target.market_ids.get(market):
                by_market[market].setdefault(str(found), target)
    feeds = Feeds(http, budget())
    today = date.today()
    try:
        for cn_game in their_games(game_id):
            # Their product id -> our target, through the catalog's market ids.
            products: dict[int, MarketTarget] = {}
            for raw in await feeds.records(cn_game, "catalog"):
                if raw.get("productType") != "card":
                    continue
                ids = market_ids(raw, cn_game)
                target = by_market[SOURCE].get(str(raw["id"])) or next(
                    (
                        by_market[m][ids[m]]
                        for m in ("cardmarket", "tcgplayer")
                        if m in ids and ids[m] in by_market[m]
                    ),
                    None,
                )
                if target is not None:
                    products[raw["id"]] = target
            quotes: list[PriceQuote] = []
            done: set[tuple[str, str]] = set()
            for raw in await feeds.records(cn_game, "prices"):
                target = products.get(raw.get("productId"))
                key = (target.set_external_id, target.printing_external_id) if target else None
                if target is None or key in done:
                    continue
                done.add(key)
                quotes += quotes_for(game_id, target, raw.get("pricesByFinish") or {}, today)
                if len(quotes) >= 2000:
                    yield quotes
                    quotes = []
            if quotes:
                yield quotes
    except BudgetSpent as exc:
        log.warning("%s; CardNexus prices wait for the next run", exc)


source = CardNexusSource()
