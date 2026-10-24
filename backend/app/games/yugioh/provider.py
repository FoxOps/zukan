"""Yu-Gi-Oh! (Konami), as two games: the Trading Card Game (Europe, the Americas, Oceania:
English, French, German, Italian, Spanish, Portuguese) and the Official Card Game (Japan
and Asia: Japanese, Korean, Chinese, Asian English).

TCG catalog: YGOPRODeck (`ygoprodeck.py`) for every card, set and printing, with French,
German, Italian and Portuguese names; YGOJSON (`ygojson.py`) for Spanish names and the
European languages and editions of each printing.
OCG catalog: YGOJSON's Japanese, Korean, Chinese and Asian English printings, one set per
code prefix ("BETB-KR"); Konami's database (`konami.py`) for the names and printings of
cards newer than YGOJSON. Both games share one download of each source (`shared.py`).

Cards are keyed on their password (YGOPRODeck id, "46986414"); OCG cards without one on
YGOJSON's id. A printing is a set code with one rarity ("LOB-EN001" Ultra Rare and Secret
Rare are two printings, as on Cardmarket); finishes are the editions (1st, Unlimited,
Limited). Sets are keyed on their name: YGOPRODeck reuses codes (tins of several years).

Prices: Cardmarket's public price guide (game 3, matched by expansion and name, TCG sets
only) and TCGplayer's market price from YGOPRODeck's `set_price` (USD).
"""

import html
import logging
import re
import time
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
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
    SetData,
)
from app.games.ocr import by_position, clean, has_cjk, letter_ratio, script_language
from app.games.yugioh import konami, shared, ygoprodeck
from app.games.yugioh.codes import CODE, OCG_REGIONS, REGIONS, prefix_of, tag
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
# Languages of each game ("en" of the OCG: Asian English printings, "-AE" codes).
TCG_LANGUAGES = ["en", "fr", "de", "it", "pt", "es"]
OCG_LANGUAGES = ["ja", "ko", "zh-hans", "zh-hant", "en"]
ASIAN_LANGUAGES = {"ja", "ko", "zh-hans", "zh-hant"}
# TCG printings whose editions no source gives.
GUESSED_FINISHES = ["first", "unlimited"]
CATALOG_TTL = 3600
# The TCG catalog of the last sync, for price runs.
_cached: tuple[float, CatalogBatch] | None = None
TCG, OCG = "tcg", "ocg"

# Spell and Trap: YGOPRODeck has no symbol; Konami's card database has (Fandom shows the
# same ones, but refuses scripts). Drawn for Zukan as fallback (scripts/draw_color_symbols.py).
KONAMI_ICON_URL = "https://www.db.yugioh-card.com/yugiohdb/external/image/parts/attribute"
SYMBOLS = Path(__file__).parent / "symbols"
# Languages of TCG printings, sold on Cardmarket and TCGplayer.
EUROPEAN_LANGS = ["en", "fr", "de", "it", "pt", "es"]
TCG_LANGS = set(EUROPEAN_LANGS)
_PASSWORD = re.compile(r"^\s*([0-9]{8})\s*$")


class YugiohSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TCG_YUGIOH_", env_file=".env", extra="ignore")

    # Languages of the TCG game. Asian languages listed here (one game had them all
    # before 0.17.0) are the OCG game's when `ocg_languages` is not set.
    languages: list[str] = TCG_LANGUAGES
    # Languages of the OCG game (~85k printings).
    ocg_languages: list[str] | None = None
    # Konami database pages read a day for cards newer than YGOJSON (0: never).
    konami_daily_requests: int = 300

    def tcg(self) -> list[str]:
        return [lang for lang in TCG_LANGUAGES if lang in self.languages]

    def ocg(self) -> list[str]:
        if self.ocg_languages is not None:
            return [lang for lang in OCG_LANGUAGES if lang in self.ocg_languages]
        asian = ASIAN_LANGUAGES & set(self.languages)
        return (
            [lang for lang in OCG_LANGUAGES if lang in asian or lang == "en"]
            if asian
            else (list(OCG_LANGUAGES))
        )


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
    # YGOPRODeck writes some names with HTML entities ("Legendary 5D&apos;s Decks").
    return html.unescape(name)


def _yj_names(yj: YgoJson | None, by_password: dict[int, CardData], wanted: set[str]) -> None:
    """Names YGOJSON knows (Spanish, Asian languages), for the cards of these passwords."""
    for yc in yj.cards.values() if yj else []:
        card = next((by_password[p] for p in yc.passwords if p in by_password), None)
        if card is not None:
            for lang, name in yc.names.items():
                if lang in wanted:
                    card.names.setdefault(lang, name)


def _card(raw: dict[str, Any], names: dict[str, str]) -> CardData:
    return CardData(
        external_id=str(raw["id"]),
        name=raw["name"],
        colors=_colors(raw),
        attributes=_attributes(raw),
        names=dict(names),
    )


def build_tcg(
    raw_cards: list[dict[str, Any]],
    raw_sets: list[dict[str, Any]],
    translations: dict[str, dict[int, str]] | None = None,
    yj: YgoJson | None = None,
    languages: list[str] = TCG_LANGUAGES,
) -> CatalogBatch:
    """The TCG catalog: YGOPRODeck cards and sets, names by language, European languages
    and editions of the printings from YGOJSON. Sets stay keyed on their YGOPRODeck name."""
    translations = translations or {}
    wanted = set(languages) | {"en"}
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
        card = _card(raw, {"en": raw["name"]})
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
            found = yj.european_of(number, rarity) if yj else None
            langs, finishes = found or (["en"], [])
            attributes: dict[str, Any] = {} if finishes else {"finishes_guessed": True}
            if found is None and yj is not None and not yj.knows_set(number):
                # YGOJSON (frozen in 2026-04) has no European printing of the set at all:
                # newer TCG sets are printed in every European language.
                langs = EUROPEAN_LANGS
                attributes["languages_guessed"] = True
            printing = PrintingData(
                external_id=external_id,
                set_external_id=set_name,
                collector_number=number,
                rarity=rarity,
                finishes=list(finishes) or list(GUESSED_FINISHES),
                languages=[lang for lang in langs if lang in wanted] or ["en"],
                images={"en": image} if image else {},
                attributes=attributes,
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
    _yj_names(yj, by_password, wanted)
    return CatalogBatch(sets=list(sets.values()), cards=list(cards.values()), prices=quotes)


def build_ocg(
    raw_cards: list[dict[str, Any]],
    yj: YgoJson | None = None,
    pages: dict[int, dict[str, Page]] | None = None,
    languages: list[str] = OCG_LANGUAGES,
) -> CatalogBatch:
    """The OCG catalog: Japanese, Korean, Chinese and Asian English printings (YGOJSON,
    Konami pages by Konami id and locale), each code in the set of its prefix
    ("BETB-KR024" in "BETB-KR"). Cards keep their password (YGOPRODeck's data); OCG cards
    without one yet are keyed on YGOJSON's id."""
    pages = pages or {}
    wanted = set(languages)
    # YGOPRODeck's English names are the Asian English cards' too.
    english = "en" in wanted
    by_password = {
        raw["id"]: _card(raw, {"en": raw["name"]} if english else {}) for raw in raw_cards
    }
    cards = {c.external_id: c for c in by_password.values()}
    sets: dict[str, SetData] = {}
    taken: set[tuple[str, str]] = set()

    def add(
        card: CardData,
        set_data: SetData,
        number: str,
        rarity: str | None,
        lang: str,
        finishes: list[str],
        image: str | None,
    ) -> None:
        external_id = f"{number}~{tag(rarity)}"
        if (set_data.external_id, external_id) in taken:
            return
        taken.add((set_data.external_id, external_id))
        sets.setdefault(set_data.external_id, set_data)
        card.printings.append(
            PrintingData(
                external_id=external_id,
                set_external_id=set_data.external_id,
                collector_number=number,
                rarity=rarity,
                finishes=finishes,
                languages=[lang],
                images={lang: image} if image else {},
            )
        )

    if yj is not None:
        _yj_names(yj, by_password, wanted)
        by_uuid: dict[str, CardData] = {}
        for yc in yj.cards.values():
            card = next((by_password[p] for p in yc.passwords if p in by_password), None)
            if card is not None:
                by_uuid[yc.uuid] = card
        for ys in yj.sets:
            if ys.lang not in wanted:
                continue
            own_set = SetData(ys.external_id, ys.external_id, ys.name, ys.lang, ys.release_date)
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
                        name=yc.names.get("en")
                        or yc.names.get("ja")
                        or next(iter(yc.names.values()), "?"),
                        colors=_ocg_colors(yc.attributes),
                        attributes=yc.attributes,
                        names=names,
                    )
                add(card, own_set, yp.number, yp.rarity, ys.lang, yp.finishes, yp.image)

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
                if not match or (match.group(2) or "") not in OCG_REGIONS:
                    continue
                if REGIONS[match.group(2)] != lang:
                    continue
                prefix = prefix_of(pack.number)
                rarity = KONAMI_CODES.get(pack.rarity or "", pack.rarity)
                own_set = SetData(prefix, prefix, pack.name or prefix, lang, _date(pack.released))
                add(card, own_set, pack.number, rarity, lang, ["unlimited"], None)

    return CatalogBatch(sets=list(sets.values()), cards=[c for c in cards.values() if c.printings])


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
    group = "yugioh"
    group_name = "Yu-Gi-Oh!"
    colors = [
        ColorDef("dark", "Dark", "#5B3A8E", f"{ICON_URL}/DARK.jpg"),
        ColorDef("light", "Light", "#D9B53B", f"{ICON_URL}/LIGHT.jpg"),
        ColorDef("earth", "Earth", "#8A6A3B", f"{ICON_URL}/EARTH.jpg"),
        ColorDef("water", "Water", "#2F7FD0", f"{ICON_URL}/WATER.jpg"),
        ColorDef("fire", "Fire", "#D2412F", f"{ICON_URL}/FIRE.jpg"),
        ColorDef("wind", "Wind", "#3F9E4F", f"{ICON_URL}/WIND.jpg"),
        ColorDef("divine", "Divine", "#C8A24A", f"{ICON_URL}/DIVINE.jpg"),
        # Konami's own (魔 / 罠); drawn ones while it cannot be reached.
        ColorDef(
            "spell",
            "Spell",
            "#1D9A86",
            f"{KONAMI_ICON_URL}/attribute_icon_spell.png",
            icon_file=SYMBOLS / "spell.svg",
        ),
        ColorDef(
            "trap",
            "Trap",
            "#B5307A",
            f"{KONAMI_ICON_URL}/attribute_icon_trap.png",
            icon_file=SYMBOLS / "trap.svg",
        ),
    ]
    finishes = [
        FinishDef("unlimited", "Unlimited"),
        FinishDef("first", "1st Edition"),
        FinishDef("limited", "Limited Edition"),
    ]
    rarities = RARITIES
    rarity_in_printing = True
    filters = [
        FilterDef("type", "Type", "type"),
        FilterDef("race", "Monster type", "race"),
        FilterDef("archetype", "Archetype", "archetype"),
        FilterDef("rarity", "Rarity"),
    ]
    cardmarket_path = "YuGiOh"
    # 2: TCG / OCG sets, Korean and Chinese printings in the TCG sets, European
    # languages of sets YGOJSON lacks.
    # 3: one game each (TCG, OCG), Asian printings in OCG sets of their code.
    catalog_version = 3
    legal_notice = LEGAL_NOTICE
    # No `text_attribute`: printings carry the text of their time (errata, "Graveyard"
    # became "GY"), so other sources' texts are not compared.

    def __init__(self, region: str = TCG):
        self.region = region
        if region == TCG:
            self.id, self.name, self.region_label = "yugioh", "Yu-Gi-Oh! TCG", "TCG"
            self.short_names = ["yugioh", "ygo", "yu-gi-oh"]
            self.price_sources = ["cardmarket", "tcgplayer"]
            self.source_keys = {"tcgcsv": 2, "apitcg": "yugioh"}
        else:
            self.id, self.name, self.region_label = "yugioh-ocg", "Yu-Gi-Oh! OCG", "OCG"
            self.short_names = ["ocg", "ygocg", "yugiohocg"]
            # Cardmarket and TCGplayer sell the TCG printings.
            self.price_sources = []
            self.source_keys = {}
        self.image_fallback = "en" if region == TCG else "ja"

    @property
    def languages(self) -> list[str]:
        settings = YugiohSettings()
        return settings.tcg() if self.region == TCG else settings.ocg()

    async def _catalog(self, http: httpx.AsyncClient) -> CatalogBatch:
        settings = YugiohSettings()
        raw_cards = await shared.cards(http)
        yj = await shared.ygojson_data(http)
        if self.region == OCG:
            languages = settings.ocg()
            cache = konami.Cache()
            if settings.konami_daily_requests > 0:
                wanted = konami_wanted(raw_cards, yj, languages)
                read = await konami.fill(http, cache, wanted, settings.konami_daily_requests)
                log.info("Konami database: %s pages read, %s cards to go", read, len(wanted) - read)
            pages = {int(cid): by_lang for cid, by_lang in cache.pages.items()}
            return build_ocg(raw_cards, yj, pages, languages)
        languages = settings.tcg()
        translations: dict[str, dict[int, str]] = {}
        for lang in ygoprodeck.LANGUAGES:
            if lang in languages:
                try:
                    translations[lang] = await ygoprodeck.names(http, lang)
                except httpx.HTTPError as exc:
                    log.warning("YGOPRODeck %s names unavailable: %s", lang, exc)
        raw_sets = await ygoprodeck.sets(http)
        return build_tcg(raw_cards, raw_sets, translations, yj, languages)

    async def _cardmarket_quotes(
        self, http: httpx.AsyncClient, catalog: CatalogBatch
    ) -> list[PriceQuote]:
        products = await cardmarket.products(http, CARDMARKET_GAME)
        guides = await cardmarket.price_guide(http, CARDMARKET_GAME)
        tcg = CatalogBatch(
            cards=[
                CardData(
                    c.external_id,
                    c.name,
                    printings=[p for p in c.printings if not TCG_LANGS.isdisjoint(p.languages)],
                )
                for c in catalog.cards
            ]
        )
        return cardmarket.match_products(tcg, products, guides, {}, lambda finish: "", _price_order)

    async def fetch_catalog(self, http: httpx.AsyncClient) -> AsyncIterator[CatalogBatch]:
        global _cached
        batch = await self._catalog(http)
        if self.region == TCG:
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
        if self.region != TCG:
            return
        if _cached is None or time.monotonic() - _cached[0] > CATALOG_TTL:
            # Prices concern the printings only: no translations or YGOJSON data needed.
            raw_cards, raw_sets = await shared.cards(http), await ygoprodeck.sets(http)
            _cached = (time.monotonic(), build_tcg(raw_cards, raw_sets))
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
        """Set codes and stored collector numbers of a printed code. TCG: European
        printings are languages of the English one ("BETB-FR024" -> "BETB-EN024"). OCG:
        each code is in the set of its prefix ("BETB-KR024" in "BETB-KR")."""
        printed = text.strip().upper()
        match = CODE.fullmatch(printed)
        if not match:
            return None
        code, region, digits = match.group(1), match.group(2) or "", match.group(3)
        if (region in OCG_REGIONS) != (self.region == OCG):
            return None
        if self.region == OCG:
            return [f"{code}-{region}"], [printed]
        numbers = [f"{code}-EN{digits}", f"{code}-E{digits}", f"{code}-{digits}", printed]
        return [code], list(dict.fromkeys(numbers))

    def parse_ocr(self, lines: list[OcrLine]) -> OcrHints:
        ordered = by_position([OcrLine(clean(line.text), line.left, line.top) for line in lines])
        text = " ".join(line.text for line in ordered)
        recognized = "konami" in text.casefold()
        set_code = number = lang = None
        ocg = False
        for line in ordered:
            match = CODE.search(line.text.upper())
            if match:
                code, region, digits = match.group(1), match.group(2) or "", match.group(3)
                lang = REGIONS.get(region)
                ocg = region in OCG_REGIONS
                if ocg:
                    set_code, number = f"{code}-{region}", f"{code}-{region}{digits}"
                else:
                    # European printings are stored under their English code ("FR" ->
                    # "EN", old one-letter codes "F" -> "E").
                    english = {2: "EN", 1: "E"}.get(len(region), "")
                    set_code, number = code, f"{code}-{english}{digits}"
                recognized = True
                break
            if _PASSWORD.match(line.text):
                recognized = True
        if lang is None:
            lang = script_language(ordered)
            ocg = lang is not None
            lang = lang or "en"
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
            # A card of the other game (OCG printed codes or Asian writing) is that one's.
            recognized=recognized and ocg == (self.region == OCG),
        )
