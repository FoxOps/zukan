"""Fill the "zh-hans" section of backend/app/games/pokemon/card_names.json: English names
of mainland (Simplified) Chinese Pokémon cards that species names cannot translate.

    cd backend && uv run python ../scripts/pokemon_china_names.py

Other sections are left as they are (`pokemon_card_names.py` makes them). Names of the
mainland dataset (duanxr/PTCG-CHS-Datasets) are looked up, in order, in:
- the Traditional Chinese section, after conversion to Traditional characters (OpenCC):
  official Taiwan names mostly match mainland ones;
- PokeAPI item names (Simplified, then Traditional): "精灵球" = "Poké Ball";
- 52poke (https://wiki.52poke.com, CC BY-NC-SA 3.0), the Chinese community wiki: its card
  pages "<name>（TCG）" and other pages start with {{N|Chinese||Japanese|English}};
- names made of translated parts: "火箭队的超梦ex" (owner's Pokémon) = "Team Rocket's Mewtwo
  ex", "厄诡椪 碧草面具ex" = "Ogerpon Teal Mask ex".
About 100 requests to 52poke, one a second. Run again after new mainland sets come out.
"""

import csv
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import opencc

ROOT = Path(__file__).parent.parent
TARGET = ROOT / "backend/app/games/pokemon/card_names.json"
sys.path.insert(0, str(ROOT / "backend"))
from app.games.pokemon.species import (  # noqa: E402
    basic_energy,
    derive_names,
    find_species,
    normalize_name,
)

DATASET = "https://raw.githubusercontent.com/duanxr/PTCG-CHS-Datasets/main/ptcg_chs_infos.json"
ITEMS = "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/item_names.csv"
WIKI = "https://wiki.52poke.com/api.php"
USER_AGENT = "Zukan card names (https://github.com/FoxOps/zukan)"
# PokeAPI language ids: Traditional Chinese, Simplified Chinese, English.
ITEM_LANGUAGES = {4: "zh-hant", 12: "zh-hans", 9: "en"}
# Titles per 52poke request (long requests fail behind its proxy).
BATCH = 20

# {{N|中文|...|日本語|English}}: the English name is the last field written in Latin.
_N = re.compile(r"\{\{N\|([^{}]*)\}\}")
_HAN = re.compile(r"[㐀-鿿]")
_SUFFIX = re.compile(r"\s*(ex|EX|GX|V|VMAX|VSTAR|V-UNION|BREAK|LV\.X|δ)$")


def get(url: str, form: dict | None = None) -> bytes:
    """GET, or POST of `form`; server errors retried a few times."""
    data = urllib.parse.urlencode(form).encode() if form else None
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
    raise AssertionError("unreachable")


def dataset_names() -> Counter:
    """Card name -> printings in the mainland dataset."""
    data = json.loads(get(DATASET))
    names: Counter = Counter()
    for collection in data["collections"]:
        for card in collection.get("cards") or []:
            details = card.get("details") or {}
            name = (details.get("cardName") or card.get("name") or "").strip()
            if name:
                names[normalize_name(name)] += 1
    return names


def item_names() -> dict[str, dict[str, str]]:
    """Item names per language -> English name (PokeAPI)."""
    rows = list(csv.DictReader(io.StringIO(get(ITEMS).decode())))
    by_item: dict[str, dict[str, str]] = {}
    for row in rows:
        lang = ITEM_LANGUAGES.get(int(row["local_language_id"]))
        if lang:
            by_item.setdefault(row["item_id"], {})[lang] = normalize_name(row["name"])
    items: dict[str, dict[str, str]] = {"zh-hans": {}, "zh-hant": {}}
    for names in by_item.values():
        if "en" in names:
            for lang in items:
                if lang in names:
                    items[lang].setdefault(names[lang], names["en"])
    return items


def english_of(template: str) -> str | None:
    fields = [f.strip() for f in template.split("|")]
    latin = [f for f in fields if f and not _HAN.search(f) and re.search(r"[A-Za-z]", f)]
    return normalize_name(latin[-1]) if latin else None


def wiki_names(names: list[str]) -> dict[str, str]:
    """English names from 52poke pages "<name>（TCG）", else "<name>"."""
    found: dict[str, str] = {}
    titles = [t for name in names for t in (f"{name}（TCG）", name)]
    for start in range(0, len(titles), BATCH):
        query = {
            "action": "query",
            "titles": "|".join(titles[start : start + BATCH]),
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "redirects": 1,
            "format": "json",
            "formatversion": 2,
        }
        data = json.loads(get(WIKI, query))["query"]
        # Asked title -> page title, through normalization and redirects.
        target = {t: t for t in titles[start : start + BATCH]}
        for step in ("normalized", "redirects"):
            moves = {m["from"]: m["to"] for m in data.get(step, [])}
            target = {asked: moves.get(page, page) for asked, page in target.items()}
        english: dict[str, str] = {}
        for page in data.get("pages", []):
            text = (page.get("revisions") or [{}])[0].get("slots", {}).get("main", {})
            match = _N.search(text.get("content", ""))
            if match and (name := english_of(match.group(1))):
                english[page["title"]] = name
        for asked, page in target.items():
            name = asked.removesuffix("（TCG）")
            if page in english and name not in found:
                found[name] = english[page]
        time.sleep(1)
    return found


def species_english(name: str) -> str | None:
    return derive_names(name, "zh-hans", find_species(name, "zh-hans")).get("en")


def main() -> None:
    table = json.loads(TARGET.read_text())
    names = dataset_names()
    left = sorted(
        n for n in names if _HAN.search(n) and not species_english(n) and not basic_energy(n)
    )
    print(f"dataset: {len(names)} names, {len(left)} not translated by species names")

    to_traditional = opencc.OpenCC("s2t")
    traditional = table.get("zh-hant", {})
    items = item_names()
    found: dict[str, str] = {}
    for name in left:
        hant = normalize_name(to_traditional.convert(name))
        english = traditional.get(hant) or items["zh-hans"].get(name) or items["zh-hant"].get(hant)
        if english:
            found[name] = english
    print(f"Traditional table and items: {len(found)}")

    wiki = wiki_names([n for n in left if n not in found])
    found |= wiki
    print(f"52poke: {len(wiki)}")

    # Names made of parts: "<owner>的<Pokémon>", "<Pokémon> <form>".
    parts = {
        p for n in left if n not in found for p in re.split(r"的|\s+", _SUFFIX.sub("", n)) if p
    }
    known = {**found, **wiki_names([p for p in parts if p not in found and not species_english(p)])}

    def part(text: str) -> str | None:
        return known.get(text) or species_english(text)

    composed = 0
    for name in left:
        if name in found:
            continue
        suffix = _SUFFIX.search(name)
        stem = _SUFFIX.sub("", name)
        if "的" in stem:
            owner, _, pokemon = stem.partition("的")
            words = [f"{part(owner)}'s" if part(owner) else None, part(pokemon)]
        else:
            words = [part(p) for p in stem.split()] if " " in stem else [None]
        if all(words):
            found[name] = " ".join(words) + (f" {suffix.group(1)}" if suffix else "")
            composed += 1
    print(f"composed: {composed}")

    missing = Counter({n: names[n] for n in left if n not in found})
    print(f"zh-hans: {len(found)} names, {len(missing)} left ({sum(missing.values())} printings)")
    print("most printed left:", ", ".join(n for n, _ in missing.most_common(30)))
    table["zh-hans"] = dict(sorted(found.items()))
    TARGET.write_text(json.dumps(table, ensure_ascii=False, indent=0, sort_keys=True) + "\n")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
