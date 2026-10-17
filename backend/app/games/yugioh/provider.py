"""Yu-Gi-Oh! Trading Card Game (Konami).

Catalog: YGOPRODeck (`ygoprodeck.py`) for every TCG card, set and printing, with French,
German, Italian and Portuguese names; YGOJSON (`ygojson.py`) for Spanish, Japanese, Korean
and Chinese names and the OCG printings (Japanese, Korean, Chinese sets, stored as sets
of their own like Pokémon's Asian sets); Konami's database (`konami.py`) for the names and
OCG printings of cards newer than YGOJSON.

Cards are keyed on their password (YGOPRODeck id, "46986414"); OCG cards without one on
YGOJSON's id. A printing is a set code with one rarity ("LOB-EN001" Ultra Rare and Secret
Rare are two printings, as on Cardmarket); finishes are the editions (1st, Unlimited,
Limited). Sets are keyed on their name: YGOPRODeck reuses codes (tins of several years).

Prices: Cardmarket's public price guide (game 3, matched by expansion and name, TCG sets
only) and TCGplayer's market price from YGOPRODeck's `set_price` (USD).
"""

import logging
import re
import time
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.games import cardmarket
from app.games.base import (
    CardData,
    CatalogBatch,
    ColorDef,
    FilterDef,
    FinishDef,
    OcrHints,
    OcrLine,
    PriceQuote,
    PriceTarget,
    PrintingData,
    PrintingMove,
    SetData,
)
from app.games.ocr import by_position, clean, has_cjk, letter_ratio, script_language
from app.games.yugioh import konami, ygojson, ygoprodeck
from app.games.yugioh.codes import (
    ASIAN_REGIONS,
    CODE,
    REGIONS,
    base_code,
    number_key,
    prefix_of,
    rarity_key,
    tag,
)
from app.games.yugioh.konami import Page
from app.games.yugioh.rarities import KONAMI_CODES, RARITIES, clean_rarity
from app.games.yugioh.ygojson import YgoJson
from app.models import Printing

log = logging.getLogger(__name__)

CARDMARKET_GAME = 3
ICON_URL = "https://images.ygoprodeck.com/images/cards/icons/attributes"
LEGAL_NOTICE = (
    "Yu-Gi-Oh! is a trademark of Konami Digital Entertainment, Inc. Zukan is not produced, "
    "endorsed, supported or affiliated with Konami. Card data from YGOPRODeck, YGOJSON and "
    "the official Yu-Gi-Oh! card database."
)
DEFAULT_LANGUAGES = ["en", "fr", "de", "it", "pt", "es", "ja", "ko", "zh-hans", "zh-hant"]
# TCG printings whose editions no source gives.
GUESSED_FINISHES = ["first", "unlimited"]
CATALOG_TTL = 3600
_cached: tuple[float, CatalogBatch] | None = None

# Languages of TCG printings sold on Cardmarket and TCGplayer.
TCG_LANGS = {"en", "fr", "de", "it", "pt", "es"}
_PASSWORD = re.compile(r"^\s*([0-9]{8})\s*$")


class YugiohSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TCG_YUGIOH_", env_file=".env", extra="ignore")

    # Name languages and OCG sets to import (ja, ko, zh-hans, zh-hant add ~85k printings).
    languages: list[str] = DEFAULT_LANGUAGES
    # Konami database pages read a day for cards newer than YGOJSON (0: never).
    konami_daily_requests: int = 300


def _decimal(value: Any) -> Decimal | None:
    try:
        price = Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None
    return price if price > 0 else None


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def _colors(card: dict[str, Any]) -> list[str]:
    kind = (card.get("type") or "").casefold()
    if "spell" in kind:
        return ["spell"]
    if "trap" in kind:
        return ["trap"]
    attribute = (card.get("attribute") or "").casefold()
    return [attribute] if attribute else []


def _attributes(card: dict[str, Any]) -> dict[str, Any]:
    info = ygoprodeck.misc(card)
    values = {
        "type": card.get("humanReadableCardType") or card.get("type"),
        "frame": card.get("frameType"),
        "race": card.get("race"),
        "attribute": card.get("attribute"),
        "level": card.get("level"),
        "link": card.get("linkval"),
        "scale": card.get("scale"),
        "atk": card.get("atk"),
        "def": card.get("def"),
        "archetype": card.get("archetype"),
        "desc": card.get("desc"),
        "konami_id": info.get("konami_id"),
    }
    return {k: v for k, v in values.items() if v not in (None, "", [])}


def _ocg_colors(attributes: dict[str, Any]) -> list[str]:
    kind = (attributes.get("card_type") or "").casefold()
    if kind in ("spell", "trap"):
        return [kind]
    attribute = (attributes.get("attribute") or "").casefold()
    return [attribute] if attribute else []


def tcg_name(name: str) -> str:
    return f"{name} (TCG)"


def ocg_name(name: str) -> str:
    return f"{name} (OCG)"


class _Placer:
    """Puts Korean and Chinese printings (YGOJSON, Konami) in the TCG set of their code:
    "BETB-KR024" is a language of "BETB-EN024" when it is the same card and rarity, else a
    printing of its own in that set. Codes no TCG set has keep a set of their own.
    Japanese printings make the OCG sets."""

    def __init__(
        self, cards: dict[str, CardData], sets: dict[str, SetData], taken: set[tuple[str, str]]
    ):
        self.sets = sets
        self.taken = taken
        self.moved: list[PrintingMove] = []
        # TCG printings by code without region, with their card.
        self.by_number: dict[str, list[tuple[CardData, PrintingData]]] = {}
        # TCG sets by code ("BETB").
        self.by_code: dict[str, list[str]] = {}
        self.added: dict[tuple[str, str], PrintingData] = {}
        for s in sets.values():
            self.by_code.setdefault(s.code.upper(), []).append(s.external_id)
        for card in cards.values():
            for printing in card.printings:
                if printing.collector_number:
                    key = number_key(printing.collector_number)
                    self.by_number.setdefault(key, []).append((card, printing))

    def place(
        self,
        card: CardData,
        old_set: str,
        number: str,
        rarity: str | None,
        lang: str,
        finishes: list[str],
        image: str | None,
    ) -> bool:
        """Add an Asian printing (stored in `old_set` before) to its TCG set. False when
        no TCG set has its code."""
        old_id = f"{number}~{tag(rarity)}"
        same_card = [(c, p) for c, p in self.by_number.get(number_key(number), []) if c is card]
        match = next((p for _, p in same_card if rarity_key(p.rarity) == rarity_key(rarity)), None)
        if match is None:
            if same_card:
                target = same_card[0][1].set_external_id
            elif len(found := self.by_code.get(base_code(number), [])) == 1:
                target = found[0]
            else:
                return False
            match = self.added.get((target, old_id))
            if match is None:
                match = self.added[(target, old_id)] = PrintingData(
                    external_id=old_id,
                    set_external_id=target,
                    collector_number=number,
                    rarity=rarity,
                    finishes=[],
                    languages=[],
                    attributes={},
                )
                self.taken.add((target, old_id))
                card.printings.append(match)
        if lang not in match.languages:
            match.languages.append(lang)
        match.finishes.extend(f for f in finishes if f not in match.finishes)
        if image:
            match.images.setdefault(lang, image)
        match.attributes.setdefault("numbers", {})[lang] = number
        if (match.set_external_id, match.external_id) != (old_set, old_id):
            self.moved.append(
                PrintingMove(old_set, old_id, match.set_external_id, match.external_id)
            )
        return True


def build_catalog(
    raw_cards: list[dict[str, Any]],
    raw_sets: list[dict[str, Any]],
    translations: dict[str, dict[int, str]] | None = None,
    yj: YgoJson | None = None,
    pages: dict[int, dict[str, Page]] | None = None,
    languages: list[str] = DEFAULT_LANGUAGES,
) -> CatalogBatch:
    """Catalog from YGOPRODeck cards and sets, names by language, YGOJSON and Konami
    pages (by Konami id and locale).

    TCG sets ("Burst of Destiny (TCG)") hold every language printed with their code:
    European (YGOPRODeck, YGOJSON), Korean and Chinese (YGOJSON, Konami). Japanese sets
    are the OCG ones ("バースト・オブ・デスティニー (OCG)"). Sets stay keyed on their
    YGOPRODeck name / Asian code prefix."""
    translations = translations or {}
    pages = pages or {}
    wanted = set(languages)
    sets: dict[str, SetData] = {}
    for raw in raw_sets:
        name = raw["set_name"]
        sets[name] = SetData(
            external_id=name,
            code=raw.get("set_code") or name,
            name=tcg_name(name),
            lang="en",
            release_date=_date(raw.get("tcg_date")),
            total=raw.get("num_of_cards"),
            icon_url=None,
        )
    cards: dict[str, CardData] = {}
    by_password: dict[int, CardData] = {}
    quotes: list[PriceQuote] = []
    # (set, printing id) already given to a card.
    taken: set[tuple[str, str]] = set()
    for raw in raw_cards:
        password = raw["id"]
        card = CardData(
            external_id=str(password),
            name=raw["name"],
            colors=_colors(raw),
            attributes=_attributes(raw),
            names={"en": raw["name"]},
        )
        for lang, names in translations.items():
            if lang in wanted and password in names:
                card.names[lang] = names[password]
        images = raw.get("card_images") or []
        image = images[0].get("image_url") if images else None
        seen: set[str] = set()
        for entry in raw.get("card_sets") or []:
            set_name = entry.get("set_name")
            number = entry.get("set_code")
            if not set_name or not number:
                continue
            if set_name not in sets:
                code = prefix_of(number).split("-")[0]
                sets[set_name] = SetData(set_name, code, tcg_name(set_name), "en")
            rarity = clean_rarity(entry.get("set_rarity"))
            external_id = f"{number}~{tag(rarity)}"
            if external_id in seen:
                continue
            seen.add(external_id)
            if (set_name, external_id) in taken:
                # Two cards listed under one code and rarity (alternate artworks).
                external_id = f"{external_id}~{password}"
            taken.add((set_name, external_id))
            langs, finishes = (yj.european_of(number, rarity) if yj else None) or (["en"], [])
            printing = PrintingData(
                external_id=external_id,
                set_external_id=set_name,
                collector_number=number,
                rarity=rarity,
                finishes=list(finishes) or list(GUESSED_FINISHES),
                languages=[lang for lang in langs if lang in wanted] or ["en"],
                images={"en": image} if image else {},
                attributes={} if finishes else {"finishes_guessed": True},
            )
            card.printings.append(printing)
            price = _decimal(entry.get("set_price"))
            if price is not None:
                for finish in printing.finishes:
                    quotes.append(
                        PriceQuote(
                            set_name,
                            external_id,
                            finish,
                            trend=price,
                            currency="USD",
                            source="tcgplayer",
                        )
                    )
        cards[card.external_id] = card
        by_password[password] = card

    placer = _Placer(cards, sets, taken)
    if yj is not None:
        _add_ygojson(yj, cards, by_password, sets, wanted, taken, placer)
    _add_konami(pages, cards, sets, wanted, taken, placer)
    return CatalogBatch(
        sets=list(sets.values()),
        cards=list(cards.values()),
        prices=quotes,
        moved=placer.moved,
    )


def _add_ygojson(
    yj: YgoJson,
    cards: dict[str, CardData],
    by_password: dict[int, CardData],
    sets: dict[str, SetData],
    wanted: set[str],
    taken: set[tuple[str, str]],
    placer: _Placer,
) -> None:
    by_uuid: dict[str, CardData] = {}
    for yc in yj.cards.values():
        card = next((by_password[p] for p in yc.passwords if p in by_password), None)
        if card is not None:
            for lang, name in yc.names.items():
                if lang in wanted:
                    card.names.setdefault(lang, name)
            by_uuid[yc.uuid] = card
    for ys in yj.sets:
        if ys.lang not in wanted:
            continue
        name = ocg_name(ys.name) if ys.lang == "ja" else tcg_name(ys.name)
        own_set = SetData(ys.external_id, ys.external_id, name, ys.lang, ys.release_date)
        for yp in ys.printings:
            # Codes not known yet when YGOJSON read them ("DDS2-JP0??").
            if "?" in yp.number:
                continue
            card = by_uuid.get(yp.card)
            if card is None:
                yc = yj.cards.get(yp.card)
                if yc is None:
                    continue
                # OCG card YGOPRODeck does not have (no password yet).
                names = {lang: n for lang, n in yc.names.items() if lang in wanted}
                card = by_uuid[yc.uuid] = cards[f"ygojson:{yc.uuid}"] = CardData(
                    external_id=f"ygojson:{yc.uuid}",
                    name=names.get("en")
                    or yc.names.get("ja")
                    or next(iter(yc.names.values()), "?"),
                    colors=_ocg_colors(yc.attributes),
                    attributes=yc.attributes,
                    names=names,
                )
            if ys.lang != "ja" and placer.place(
                card, ys.external_id, yp.number, yp.rarity, ys.lang, yp.finishes, yp.image
            ):
                continue
            external_id = f"{yp.number}~{tag(yp.rarity)}"
            if (ys.external_id, external_id) in taken:
                continue
            taken.add((ys.external_id, external_id))
            sets.setdefault(ys.external_id, own_set)
            card.printings.append(
                PrintingData(
                    external_id=external_id,
                    set_external_id=ys.external_id,
                    collector_number=yp.number,
                    rarity=yp.rarity,
                    finishes=yp.finishes,
                    languages=[ys.lang],
                    images={ys.lang: yp.image} if yp.image else {},
                )
            )


def _add_konami(
    pages: dict[int, dict[str, Page]],
    cards: dict[str, CardData],
    sets: dict[str, SetData],
    wanted: set[str],
    taken: set[tuple[str, str]],
    placer: _Placer,
) -> None:
    by_konami = {
        c.attributes["konami_id"]: c for c in cards.values() if "konami_id" in c.attributes
    }
    for cid, by_lang in pages.items():
        card = by_konami.get(cid)
        if card is None:
            continue
        for lang, page in by_lang.items():
            if lang not in wanted:
                continue
            if page.name:
                card.names.setdefault(lang, page.name)
            for pack in page.packs:
                match = CODE.search(pack.number)
                if not match or (match.group(2) or "") not in ASIAN_REGIONS:
                    continue
                if REGIONS[match.group(2)] != lang:
                    continue
                prefix = prefix_of(pack.number)
                rarity = KONAMI_CODES.get(pack.rarity or "", pack.rarity)
                if lang != "ja" and placer.place(
                    card, prefix, pack.number, rarity, lang, ["unlimited"], None
                ):
                    continue
                external_id = f"{pack.number}~{tag(rarity)}"
                if (prefix, external_id) in taken:
                    continue
                taken.add((prefix, external_id))
                if prefix not in sets:
                    name = pack.name or prefix
                    sets[prefix] = SetData(
                        prefix,
                        prefix,
                        ocg_name(name) if lang == "ja" else tcg_name(name),
                        lang,
                        _date(pack.released),
                    )
                card.printings.append(
                    PrintingData(
                        external_id=external_id,
                        set_external_id=prefix,
                        collector_number=pack.number,
                        rarity=rarity,
                        finishes=["unlimited"],
                        languages=[lang],
                    )
                )


def konami_wanted(
    raw_cards: list[dict[str, Any]], yj: YgoJson | None, languages: list[str]
) -> list[tuple[int, str]]:
    """(Konami id, locale) of cards with no name in that locale, newest first."""
    have: dict[int, set[str]] = {}
    if yj is not None:
        for yc in yj.cards.values():
            for password in yc.passwords:
                have.setdefault(password, set()).update(yc.names)
    locales = [lang for lang in konami.LOCALES if lang in languages]
    found = []
    for raw in raw_cards:
        info = ygoprodeck.misc(raw)
        cid = info.get("konami_id")
        if not cid:
            continue
        released = info.get("ocg_date") or info.get("tcg_date") or ""
        for lang in locales:
            if lang not in have.get(raw["id"], set()):
                found.append((released, int(cid), lang))
    found.sort(key=lambda f: f[0], reverse=True)
    return [(cid, lang) for _, cid, lang in found]


def _price_order(printing: PrintingData) -> tuple[str, int]:
    """Lower rarities first within a code, like the order Cardmarket lists them."""
    ranks = {r.name.casefold(): i for i, r in enumerate(RARITIES)}
    return printing.collector_number or "", ranks.get((printing.rarity or "").casefold(), 99)


class YugiohProvider:
    id = "yugioh"
    name = "Yu-Gi-Oh!"
    colors = [
        ColorDef("dark", "Dark", "#5B3A8E", f"{ICON_URL}/DARK.jpg"),
        ColorDef("light", "Light", "#D9B53B", f"{ICON_URL}/LIGHT.jpg"),
        ColorDef("earth", "Earth", "#8A6A3B", f"{ICON_URL}/EARTH.jpg"),
        ColorDef("water", "Water", "#2F7FD0", f"{ICON_URL}/WATER.jpg"),
        ColorDef("fire", "Fire", "#D2412F", f"{ICON_URL}/FIRE.jpg"),
        ColorDef("wind", "Wind", "#3F9E4F", f"{ICON_URL}/WIND.jpg"),
        ColorDef("divine", "Divine", "#C8A24A", f"{ICON_URL}/DIVINE.jpg"),
        ColorDef("spell", "Spell", "#1D9A86"),
        ColorDef("trap", "Trap", "#B5307A"),
    ]
    finishes = [
        FinishDef("unlimited", "Unlimited"),
        FinishDef("first", "1st Edition"),
        FinishDef("limited", "Limited Edition"),
    ]
    rarities = RARITIES
    rarity_in_printing = True
    price_sources = ["cardmarket", "tcgplayer"]
    filters = [
        FilterDef("type", "Type", "type"),
        FilterDef("race", "Monster type", "race"),
        FilterDef("archetype", "Archetype", "archetype"),
        FilterDef("rarity", "Rarity"),
    ]
    cardmarket_path = "YuGiOh"
    # 2: TCG / OCG sets, Korean and Chinese printings in the TCG sets.
    catalog_version = 2
    short_names = ["yugioh", "ygo", "yu-gi-oh"]
    legal_notice = LEGAL_NOTICE
    # No `text_attribute`: printings carry the text of their time (errata, "Graveyard"
    # became "GY"), so other sources' texts are not compared.
    source_keys = {"tcgcsv": 2, "apitcg": "yugioh"}

    @property
    def languages(self) -> list[str]:
        return YugiohSettings().languages

    async def _tcg(
        self, http: httpx.AsyncClient
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return await ygoprodeck.cards(http), await ygoprodeck.sets(http)

    async def _catalog(self, http: httpx.AsyncClient) -> CatalogBatch:
        settings = YugiohSettings()
        raw_cards, raw_sets = await self._tcg(http)
        translations: dict[str, dict[int, str]] = {}
        for lang in ygoprodeck.LANGUAGES:
            if lang in settings.languages:
                try:
                    translations[lang] = await ygoprodeck.names(http, lang)
                except httpx.HTTPError as exc:
                    log.warning("YGOPRODeck %s names unavailable: %s", lang, exc)
        yj: YgoJson | None = None
        try:
            yj = await ygojson.fetch(http)
        except (httpx.HTTPError, OSError, ValueError) as exc:
            log.warning("YGOJSON unavailable: %s", exc)
        cache = konami.Cache()
        if settings.konami_daily_requests > 0:
            wanted = konami_wanted(raw_cards, yj, settings.languages)
            read = await konami.fill(http, cache, wanted, settings.konami_daily_requests)
            log.info("Konami database: %s pages read, %s cards to go", read, len(wanted) - read)
        pages = {int(cid): by_lang for cid, by_lang in cache.pages.items()}
        return build_catalog(raw_cards, raw_sets, translations, yj, pages, settings.languages)

    async def _cardmarket_quotes(
        self, http: httpx.AsyncClient, catalog: CatalogBatch
    ) -> list[PriceQuote]:
        products = await cardmarket.products(http, CARDMARKET_GAME)
        guides = await cardmarket.price_guide(http, CARDMARKET_GAME)
        # Cardmarket sells the TCG printings: OCG sets would only blur name matching.
        tcg_sets = {s.external_id for s in catalog.sets if s.lang == "en"}
        tcg = CatalogBatch(
            cards=[
                CardData(
                    c.external_id,
                    c.name,
                    printings=[
                        p
                        for p in c.printings
                        if p.set_external_id in tcg_sets and not TCG_LANGS.isdisjoint(p.languages)
                    ],
                )
                for c in catalog.cards
            ]
        )
        return cardmarket.match_products(tcg, products, guides, {}, lambda finish: "", _price_order)

    async def fetch_catalog(self, http: httpx.AsyncClient) -> AsyncIterator[CatalogBatch]:
        global _cached
        batch = await self._catalog(http)
        try:
            batch.prices += await self._cardmarket_quotes(http, batch)
        except httpx.HTTPError as exc:
            log.warning("Cardmarket price guide unavailable: %s", exc)
        _cached = (time.monotonic(), batch)
        yield batch

    async def fetch_prices(
        self, http: httpx.AsyncClient, owned: list[PriceTarget]
    ) -> AsyncIterator[list[PriceQuote]]:
        global _cached
        if _cached is None or time.monotonic() - _cached[0] > CATALOG_TTL:
            # Prices concern TCG printings only: no translations or OCG data needed.
            raw_cards, raw_sets = await self._tcg(http)
            _cached = (time.monotonic(), build_catalog(raw_cards, raw_sets))
        batch = _cached[1]
        quotes = list(batch.prices)
        try:
            quotes += await self._cardmarket_quotes(http, batch)
        except httpx.HTTPError as exc:
            log.warning("Cardmarket price guide unavailable: %s", exc)
        yield quotes

    def image_file_stems(self, printing: Printing) -> list[str]:
        return []

    def code_lookup(self, text: str) -> tuple[list[str], list[str]] | None:
        """Set codes and stored collector numbers of a printed code: European, Korean and
        Chinese printings are languages of the TCG printing ("BETB-FR024", "BETB-KR024" ->
        "BETB-EN024"), or their own printing in that set or in a set of their own."""
        printed = text.strip().upper()
        match = CODE.fullmatch(printed)
        if not match:
            return None
        code, region, digits = match.group(1), match.group(2) or "", match.group(3)
        if region == "JP":
            return [f"{code}-JP"], [printed]
        numbers = [f"{code}-EN{digits}", f"{code}-E{digits}", f"{code}-{digits}", printed]
        return [code, f"{code}-{region}"], list(dict.fromkeys(numbers))

    def parse_ocr(self, lines: list[OcrLine]) -> OcrHints:
        ordered = by_position([OcrLine(clean(line.text), line.left, line.top) for line in lines])
        text = " ".join(line.text for line in ordered)
        recognized = "konami" in text.casefold()
        set_code = number = lang = None
        for line in ordered:
            match = CODE.search(line.text.upper())
            if match:
                code, region, digits = match.group(1), match.group(2) or "", match.group(3)
                lang = REGIONS.get(region)
                if region in ASIAN_REGIONS:
                    # Japanese: OCG sets; Korean and Chinese: found by `code_lookup`.
                    base = f"{code}-{region}" if region == "JP" else code
                    set_code, number = base, f"{code}-{region}{digits}"
                else:
                    # European printings are stored under their English code ("FR" ->
                    # "EN", old one-letter codes "F" -> "E").
                    english = {2: "EN", 1: "E"}.get(len(region), "") if region != "AE" else region
                    set_code, number = code, f"{code}-{english}{digits}"
                recognized = True
                break
            if _PASSWORD.match(line.text):
                recognized = True
        if lang is None:
            lang = script_language(ordered) or "en"
        names = [
            line.text
            for line in ordered
            if len(line.text) >= 2
            and (has_cjk(line.text) or (len(line.text) >= 3 and letter_ratio(line.text) > 0.7))
            and not CODE.search(line.text.upper())
            and not line.text.startswith("©")
        ]
        return OcrHints(
            name=names[0] if names else None,
            other_names=names[1:3],
            set_code=set_code,
            collector_number=number,
            lang=lang,
            recognized=recognized,
        )
