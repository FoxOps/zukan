"""Asian card lists TCGdex lacks, read from open datasets on GitHub (downloaded by the
server itself, nothing is shipped):

- Korean: type-null/PTCG-database (MIT), `data_ko/<set>/<number>.json`, read from
  Pokémon Korea's official card search, with official image links and Pokédex numbers.
  TCGdex has 239 Korean cards and no images.
- Simplified Chinese (mainland China): duanxr/PTCG-CHS-Datasets, `ptcg_chs_infos.json`,
  232 products with pictures. TCGdex lists the mainland Chinese sets with no cards.

Both are read in full at every catalog sync (one download each, ~33 MB and ~10 MB), so
every card is seen by the sync like TCGdex's.
"""

import io
import json
import logging
import re
import tarfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

from app.core.http import get_with_retry
from app.games.base import CardData, PrintingData, SetData
from app.games.pokemon.species import card_translations, derive_names, find_species
from app.games.pokemon.types import card_colors

log = logging.getLogger(__name__)

KOREAN_ARCHIVE = "https://codeload.github.com/type-null/PTCG-database/tar.gz/refs/heads/main"
CHINESE_REPO = "https://raw.githubusercontent.com/duanxr/PTCG-CHS-Datasets/main"
CHINESE_DATA = f"{CHINESE_REPO}/ptcg_chs_infos.json"


def artists(names: list[str] | None) -> str | None:
    """Illustrators as one text, cut to the column size (promo collages credit dozens)."""
    text = ", ".join(n.strip() for n in names or [] if n and n.strip())
    if len(text) > 255:
        text = text[:254].rsplit(", ", 1)[0] + "…"
    return text or None


def number_key(number: str) -> str:
    """Collector numbers compared across sources: "001" = "1"."""
    return number.strip().lstrip("0").casefold() or "0"


@dataclass
class AsianSet:
    """One set of an extra source, with its cards (full data, set id still the source's)."""

    code: str
    data: SetData
    cards: list[CardData] = field(default_factory=list)


# --- Korean -----------------------------------------------------------------------

_KO_STAGES = {"기본": "Basic", "1진화": "Stage1", "2진화": "Stage2"}
_KO_TRAINERS = (
    ("포켓몬의 도구", "Tool"),
    ("아이템", "Item"),
    ("서포트", "Supporter"),
    ("서포터", "Supporter"),
    ("스타디움", "Stadium"),
)


def _ko_category(raw: dict[str, Any]) -> tuple[str, str | None]:
    kind = raw.get("card_type") or ""
    if kind == "Pokémon" or raw.get("hp"):
        return "Pokemon", None
    if "에너지" in kind:
        return "Energy", None
    trainer = next((name for prefix, name in _KO_TRAINERS if kind.startswith(prefix)), None)
    return "Trainer", trainer


def korean_card(raw: dict[str, Any], set_id: str) -> CardData | None:
    """A card of the Korean dataset; None without a collector number (some energies)."""
    number = (raw.get("number") or "").strip()
    name = (raw.get("name") or "").strip()
    if not number or not name:
        return None
    category, trainer = _ko_category(raw)
    dex = [raw["pokedex_number"]] if raw.get("pokedex_number") else []
    attributes: dict[str, Any] = {"category": category}
    if raw.get("hp"):
        attributes["hp"] = raw["hp"]
    if raw.get("stage"):
        attributes["stage"] = _KO_STAGES.get(raw["stage"], raw["stage"])
    if trainer:
        attributes["trainerType"] = trainer
    if dex:
        attributes["dexId"] = dex
    names = card_translations(name, "ko", dex, pokemon=category == "Pokemon") | {"ko": name}
    printing = PrintingData(
        external_id=number,
        set_external_id=set_id,
        collector_number=number,
        rarity=raw.get("rarity"),
        artist=artists(raw.get("author")),
        finishes=["normal"],
        languages=["ko"],
        images={"ko": raw["img"]} if raw.get("img") else {},
    )
    return CardData(
        external_id=f"ko:{name.casefold()}",
        name=name,
        colors=card_colors(raw.get("types_en") or [], category),
        attributes=attributes,
        printings=[printing],
        names=names,
    )


def read_korean(archive: bytes) -> list[AsianSet]:
    """Sets of the Korean dataset (repository archive), in file order."""
    sets: dict[str, AsianSet] = {}
    seen: dict[str, set[str]] = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar:
            parts = member.name.split("/")
            # <repo>-<branch>/data_ko/<set>/<number>.json
            if len(parts) != 4 or parts[1] != "data_ko" or not member.name.endswith(".json"):
                continue
            file = tar.extractfile(member)
            if file is None:
                continue
            raw = json.load(file)
            code = (raw.get("set_name") or "").strip()
            if not code:
                continue
            if code not in sets:
                total = raw.get("set_total") or ""
                sets[code] = AsianSet(
                    code,
                    SetData(
                        external_id=code,
                        code=code,
                        name=(raw.get("set_full_name") or code).strip(),
                        lang="ko",
                        total=int(total) if str(total).isdigit() else None,
                        icon_url=raw.get("set_img"),
                    ),
                )
            card = korean_card(raw, code)
            if card is None:
                continue
            # Decks and promo lists reuse numbers for other cards: those get the
            # Korean card id too ("001~ST2013006017").
            printing = card.printings[0]
            taken = seen.setdefault(code, set())
            if printing.external_id in taken:
                printing.external_id = f"{printing.external_id}~{raw.get('ko_id') or len(taken)}"
            taken.add(printing.external_id)
            sets[code].cards.append(card)
    return list(sets.values())


async def korean_sets(http: httpx.AsyncClient) -> list[AsianSet]:
    response = await get_with_retry(http, KOREAN_ARCHIVE, timeout=300)
    return read_korean(response.content)


# --- Simplified Chinese -------------------------------------------------------------

# Energy types by the dataset's `attribute` code.
_CN_TYPES = {
    "1": "grass",
    "2": "fire",
    "3": "water",
    "4": "lightning",
    "5": "psychic",
    "6": "fighting",
    "7": "darkness",
    "8": "metal",
    "9": "fairy",
    "10": "dragon",
    "11": "colorless",
}
_CN_CATEGORIES = {"宝可梦": "Pokemon", "训练家": "Trainer", "能量": "Energy"}
_CN_STAGES = {"基础": "Basic", "1阶进化": "Stage1", "2阶进化": "Stage2"}
_CN_TRAINERS = {"物品": "Item", "支援者": "Supporter", "竞技场": "Stadium", "宝可梦道具": "Tool"}
# Stars after the rarity mark the foil versions of a card ("C★", "C★★").
_STARS = re.compile(r"★+$")
_CN_FOILS = {0: "normal", 1: "reverse", 2: "holo"}


def chinese_card(raw: dict[str, Any], set_id: str) -> CardData | None:
    details = raw.get("details") or {}
    name = (details.get("cardName") or raw.get("name") or "").strip()
    number = (details.get("collectionNumber") or "").split("/")[0].strip()
    if not name or not number:
        return None
    category = _CN_CATEGORIES.get(details.get("cardTypeText") or "", "Pokemon")
    attributes: dict[str, Any] = {"category": category}
    if details.get("hp"):
        attributes["hp"] = details["hp"]
    if details.get("evolveText"):
        attributes["stage"] = _CN_STAGES.get(details["evolveText"], details["evolveText"])
    if details.get("trainerTypeText"):
        trainer = details["trainerTypeText"]
        attributes["trainerType"] = _CN_TRAINERS.get(trainer, trainer)
    dex = find_species(name, "zh-hans") if category == "Pokemon" else []
    if dex:
        attributes["dexId"] = dex
    names = {"zh-hans": name}
    if dex:
        names = derive_names(name, "zh-hans", dex) | names
    rarity = details.get("rarityText") or ""
    stars = len(_STARS.search(rarity).group()) if _STARS.search(rarity) else 0
    rarity = _STARS.sub("", rarity)
    image = raw.get("image")
    color = _CN_TYPES.get(str(details.get("attribute") or ""))
    printing = PrintingData(
        external_id=number,
        set_external_id=set_id,
        collector_number=number,
        rarity=None if rarity in ("", "无标记") else rarity,
        artist=artists(details.get("illustratorName")),
        finishes=[_CN_FOILS.get(stars, "holo")],
        languages=["zh-hans"],
        images={"zh-hans": f"{CHINESE_REPO}/{image}"} if image and not stars else {},
    )
    return CardData(
        external_id=f"zh-hans:{name.casefold()}",
        name=name,
        colors=card_colors([color], category),
        attributes=attributes,
        printings=[printing],
        names=names,
    )


def _merge_versions(cards: list[CardData]) -> Iterator[CardData]:
    """One printing per collector number and name: its foil versions become finishes.
    Boxes mixing series reuse numbers for other cards: those get "<number>~<n>"."""
    by_number: dict[str, CardData] = {}
    for card in cards:
        printing = card.printings[0]
        first = by_number.get(printing.external_id)
        if first is not None and first.name != card.name:
            n = 2
            while f"{printing.external_id}~{n}" in by_number and (
                by_number[f"{printing.external_id}~{n}"].name != card.name
            ):
                n += 1
            printing.external_id = f"{printing.external_id}~{n}"
            first = by_number.get(printing.external_id)
        if first is None:
            by_number[printing.external_id] = card
            continue
        kept = first.printings[0]
        kept.finishes = sorted(
            set(kept.finishes) | set(printing.finishes), key=list(_CN_FOILS.values()).index
        )
        kept.images = kept.images or printing.images
        kept.rarity = kept.rarity or printing.rarity
    yield from by_number.values()


def read_chinese(data: dict[str, Any]) -> list[AsianSet]:
    sets = []
    for product in data.get("collections") or []:
        code = (product.get("commodityCode") or "").strip()
        if not code:
            continue
        released = product.get("salesDate")
        try:
            day = date.fromisoformat(released) if released else None
        except ValueError:
            day = None
        cards = [c for raw in product.get("cards") or [] if (c := chinese_card(raw, code))]
        merged = list(_merge_versions(cards))
        sets.append(
            AsianSet(
                code,
                SetData(
                    external_id=code,
                    code=code,
                    name=(product.get("name") or code).strip(),
                    lang="zh-hans",
                    release_date=day,
                    total=len(merged) or None,
                ),
                merged,
            )
        )
    return sets


async def chinese_sets(http: httpx.AsyncClient) -> list[AsianSet]:
    response = await get_with_retry(http, CHINESE_DATA, timeout=300)
    return read_chinese(response.json())
