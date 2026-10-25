"""Regenerate backend/app/games/pokemon/card_names.json: English names of Japanese,
Korean and Traditional Chinese Pokémon cards that species names cannot translate.

    python3 scripts/pokemon_card_names.py

Asian cards are named in English from species names (`species.derive_names`), which
leaves out Trainers, Energies and Pokémon carrying other words ("ロケット団のミュウツーex",
"오거폰 벽록의 가면 ex"). Bulbapedia's Japanese set lists give the English name of every
card by set code and number; type-null/PTCG-database (MIT) gives the Japanese, Korean and
Traditional Chinese name of the same printing (`print_key` "asia:<code>-<number>": the
Asia regions number a set identically), and of the English Pokémon card with the same
fingerprint (`card_key`). Joined, they give local name -> English name.
A local name is kept when one English name clearly wins over its printings. Item cards
named like the games' items (PokeAPI, "きずぐすり" = "Potion") fill the names left. Run again
after new sets come out (about 200 requests, one a second).

Card names from Bulbapedia (https://bulbapedia.bulbagarden.net, CC BY-NC-SA 2.5): they are
the official English card names, or Bulbapedia's translation for cards never printed in
English.
"""

import csv
import io
import json
import os
import re
import sys
import tarfile
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
TARGET = ROOT / "backend/app/games/pokemon/card_names.json"
sys.path.insert(0, str(ROOT / "backend"))
from app.games.pokemon.species import basic_energy, derive_names, normalize_name  # noqa: E402

API = "https://bulbapedia.bulbagarden.net/w/api.php"
EXPANSIONS = "List of Japanese Pokémon Trading Card Game expansions"
DATASET = "https://codeload.github.com/type-null/PTCG-database/tar.gz/refs/heads/main"
FOLDERS = {"data_jp": "ja", "data_ko": "ko", "data_tc": "zh-hant"}
ITEMS = "https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/item_names.csv"
# PokeAPI language ids -> ours (Japanese: kana names, as printed on cards).
ITEM_LANGUAGES = {1: "ja", 3: "ko", 4: "zh-hant", 9: "en"}
USER_AGENT = "Zukan card names (https://github.com/FoxOps/zukan)"
# An English name must win at least this share of a local name's printings.
MAJORITY = 0.8
# A set list is used when its English names agree with the species-derived ones this
# often: pages of sets merged into an English set (Rebellion Crash -> Rebel Clash) list
# the English numbering.
AGREEMENT = 0.9
# A Korean / Chinese set whose printings mostly differ from the Japanese ones of the same
# code and number is another set (old codes reused); others are checked card by card.
SAME_SET = 0.5
# How far a translation's text length may stray from the language's usual proportion.
LENGTH_SPREAD = 1.35
# DEBUG=<n>: print the first n ambiguous names of each language.
DEBUG = int(os.environ.get("DEBUG", "0"))

# Expansion table rows: "[[File:SV2a Pokémon Card 151 Logo.png|110px]]" then
# "ポケモンカード151<br>{{TCG|Pokémon Card 151}}"; sets released in pairs share a row
# ("SV1S Logo JP.png", "SV1V Logo JP.png", "{{TCG|Scarlet ex/Violet ex|...}}").
_LOGO = re.compile(r"\[\[File:(\S+) [^|\]]*Logo[^|\]]*\.png")
_TITLE = re.compile(r"\{\{TCG\|([^}|]+)")
_HEADER = re.compile(r"\{\{Setlist/(?:nm)?header\|title=([^|}]+)")
_ENTRY = re.compile(r"\{\{Setlist/(?:nm)?entry\|([^|}]+)\|(.*)$", re.M)
_TCG_ID = re.compile(r"\{\{TCG ID\|[^|}]*\|([^|}]+)")
_LINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]|\{\{TCG\|(?:[^|}]*\|)?([^}]+)\}\}")


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


def wikitext(page: str) -> str | None:
    query = urllib.parse.urlencode(
        {
            "action": "parse",
            "page": page,
            "prop": "wikitext",
            "format": "json",
            "formatversion": 2,
            "redirects": 1,
        }
    )
    data = json.loads(get(f"{API}?{query}"))
    time.sleep(1)
    return (data.get("parse") or {}).get("wikitext")


def number_key(number: str) -> str:
    """Leading zeros dropped: "001" and "1" are the same printing."""
    return number.strip().lstrip("0") or "0"


def expansions(text: str) -> list[tuple[str, str, str]]:
    """(code, page, set list title) of the Japanese expansions."""
    found = []
    for row in text.split("\n|-"):
        codes, title = _LOGO.findall(row), _TITLE.search(row)
        if not codes or title is None:
            continue
        page = title.group(1).strip()
        parts = page.split("/") if len(codes) > 1 else [page]
        if len(parts) != len(codes):
            parts = [page] * len(codes)
        found += [(code, page, part.strip()) for code, part in zip(codes, parts, strict=True)]
    return found


def set_list(text: str, title: str) -> str:
    """The set list of `title`: pages of Japanese sets merged into an English set
    (Shiny Treasure ex -> Paldean Fates) hold one list per set."""
    parts = _HEADER.split(text)
    sections = dict(zip(parts[1::2], parts[2::2], strict=True))
    if title in sections:
        return sections[title]
    return text if len(sections) <= 1 else ""


def english_names(text: str) -> dict[str, str]:
    """Collector number -> English name of a Bulbapedia set list."""
    found = {}
    for number, rest in _ENTRY.findall(text):
        number = number.split("/")[0].strip()
        match = _TCG_ID.search(rest)
        name = match.group(1) if match else None
        if name is None:
            link = _LINK.search(rest.split("|")[1] if "|" in rest else rest)
            name = link and (link.group(1) or link.group(2))
        if name and number:
            found.setdefault(number_key(number), name.strip())
    return found


Printings = dict[tuple[str, str], dict[str, str]]
Signatures = dict[tuple[str, str], dict[str, tuple]]


def signature(raw: dict) -> tuple:
    """What a translation keeps: illustrators, HP, Pokédex number and the numbers of the
    rules text (damage, cards drawn...); then the text length (in proportion)."""
    texts = [raw.get("effect") or ""]
    for attack in raw.get("attacks") or []:
        texts += [str(attack.get("damage") or ""), attack.get("effect") or ""]
    numbers = re.findall(r"\d+", unicodedata.normalize("NFKC", " ".join(texts)))
    authors = frozenset(a.strip().casefold() for a in raw.get("author") or [] if a.strip())
    hp, dex = raw.get("hp"), raw.get("pokedex_number")
    # "1" comes and goes with the wording ("1回", "1枚" where Korean omits it).
    length = len(re.sub(r"\s+", "", " ".join(texts)))
    return authors, str(hp or ""), str(dex or ""), frozenset(numbers) - {"1"}, length


Fingerprints = dict[str, dict[str, Counter]]


def local_names() -> tuple[Printings, Signatures, Fingerprints]:
    """From the dataset: (set code casefolded, number) -> {language: local name}, and ->
    {language: signature}; Pokémon fingerprint (`card_key`) -> {language: names}."""
    archive = tarfile.open(fileobj=io.BytesIO(get(DATASET)), mode="r:gz")
    names: Printings = defaultdict(dict)
    signatures: Signatures = defaultdict(dict)
    fingerprints: Fingerprints = defaultdict(lambda: defaultdict(Counter))
    for member in archive:
        parts = member.name.split("/")
        folder = parts[1] if len(parts) >= 3 else ""
        if not member.isfile() or not member.name.endswith(".json"):
            continue
        if folder not in FOLDERS and folder != "data_en":
            continue
        raw = json.load(archive.extractfile(member))
        key, name = raw.get("print_key") or "", (raw.get("name") or "").strip()
        if raw.get("card_key") and name:
            lang = FOLDERS.get(folder, "en")
            fingerprints[raw["card_key"]][lang][normalize_name(name)] += 1
        if not key.startswith("asia:") or not name or folder not in FOLDERS:
            continue
        code, _, number = key[5:].rpartition("-")
        printing, lang = (code.casefold(), number_key(number)), FOLDERS[parts[1]]
        names[printing].setdefault(lang, name)
        signatures[printing].setdefault(lang, signature(raw))
    return names, signatures, fingerprints


def renumbered(signatures: Signatures) -> set[tuple[str, str]]:
    """(code, language) of the Korean / Chinese sets whose numbers do not name the
    Japanese printing of the same number (old codes reused for other sets)."""
    same: Counter = Counter()
    checked: Counter = Counter()
    for (code, _), by_lang in signatures.items():
        for lang, sig in by_lang.items():
            if lang != "ja" and "ja" in by_lang:
                checked[(code, lang)] += 1
                same[(code, lang)] += sig[:4] == by_lang["ja"][:4]
    return {key for key, count in checked.items() if same[key] < SAME_SET * count}


def japanese_sets(signatures: Signatures, skipped: set[tuple[str, str]]) -> dict:
    """(code, language) -> code of the Japanese set, for the Korean / Chinese sets
    without a Japanese set of their code (Korean "bw1b" is Japanese "BW1-Bb"): the
    Japanese set whose Pokémon of the same numbers match most of theirs."""
    japanese: dict[tuple[str, tuple], set[str]] = defaultdict(set)
    local: dict[tuple[str, str], list[tuple[str, tuple]]] = defaultdict(list)
    has_japanese = {code for (code, _), by_lang in signatures.items() if "ja" in by_lang}
    for (code, number), by_lang in signatures.items():
        for lang, sig in by_lang.items():
            if not sig[1]:  # Pokémon only: HP and Pokédex number tell cards apart.
                continue
            if lang == "ja":
                japanese[(number, sig[:4])].add(code)
            elif (code, lang) in skipped or code not in has_japanese:
                local[(code, lang)].append((number, sig[:4]))
    found = {}
    for key, cards in local.items():
        votes = Counter(c for card in cards for c in japanese.get(card, ()))
        if votes and len(cards) >= 5:
            code, count = votes.most_common(1)[0]
            if count >= SAME_SET * len(cards):
                found[key] = code
    return found


def length_ratios(signatures: Signatures) -> dict[str, float]:
    """Usual rules text length of each language against Japanese (median over the
    Trainers and Energies that match otherwise)."""
    ratios: dict[str, list[float]] = defaultdict(list)
    for by_lang in signatures.values():
        japanese = by_lang.get("ja")
        for lang, sig in by_lang.items():
            trainer = japanese and not japanese[1]
            if lang != "ja" and trainer and sig[:4] == japanese[:4] and sig[4] and japanese[4]:
                ratios[lang].append(sig[4] / japanese[4])
    return {lang: sorted(values)[len(values) // 2] for lang, values in ratios.items()}


def same_card(signatures: dict[str, tuple], lang: str, ratios: dict[str, float]) -> bool:
    """Whether the `lang` printing is the Japanese one of that number: same signature and
    a text of the usual length (cards without numbers by one illustrator, "Switch" and
    "Pokémon Catcher", differ by it). No Japanese printing: trusted (the set list
    numbering was checked)."""
    japanese, local = signatures.get("ja"), signatures.get(lang)
    if lang == "ja" or japanese is None:
        return True
    if local is None or local[:4] != japanese[:4]:
        return False
    if japanese[1]:  # Pokémon: HP and Pokédex number tell them apart.
        return True
    if not (local[4] and japanese[4] and lang in ratios):
        return local[4] == japanese[4] == 0
    ratio = local[4] / japanese[4] / ratios[lang]
    return 1 / LENGTH_SPREAD <= ratio <= LENGTH_SPREAD


def agrees(english: dict[str, str], printings: dict, code: str, lang: str) -> bool:
    """Whether a set list numbers its cards like the set of this code in `lang` (checked
    on the names species translate): Korean Sun & Moon sets have numberings of their own."""
    same = checked = 0
    for number, name in english.items():
        local = printings.get((code.casefold(), number), {}).get(lang)
        derived = derive_names(local, lang, []).get("en") if local else None
        if derived:
            checked += 1
            same += normalize_name(derived).casefold() == normalize_name(name).casefold()
    return checked == 0 or same >= AGREEMENT * checked


def fold(name: str) -> str:
    """Card and game spellings differ by kana ("きずぐすり", "キズぐすり"): katakana to
    hiragana, spaces dropped."""
    name = "".join(chr(ord(c) - 0x60) if "\u30a1" <= c <= "\u30f6" else c for c in name)
    return re.sub(r"\s+", "", normalize_name(name)).casefold()


def item_names() -> dict[str, dict[str, str]]:
    """Game item names per language (folded) -> English name, from PokeAPI."""
    rows = csv.DictReader(io.StringIO(get(ITEMS).decode()))
    by_item: dict[str, dict[str, str]] = defaultdict(dict)
    for row in rows:
        lang = ITEM_LANGUAGES.get(int(row["local_language_id"]))
        if lang:
            by_item[row["item_id"]][lang] = row["name"]
    items: dict[str, dict[str, str]] = defaultdict(dict)
    for names in by_item.values():
        english = names.get("en")
        for lang, name in names.items():
            if english and lang != "en":
                items[lang].setdefault(fold(name), english_form(english))
    return items


def with_items(found: dict[str, str], names: set[str], items: dict[str, str]) -> dict[str, str]:
    """`found` plus the card names left that are item names."""
    extra = {name: items[fold(name)] for name in names - set(found) if fold(name) in items}
    return found | extra


def english_form(name: str) -> str:
    """One spelling of an English name: sources write "Nidoran Female" or "Nidoran♀",
    "Basic Fire Energy" or "Fire Energy" (the international cards' name)."""
    name = normalize_name(name).replace("Nidoran Female", "Nidoran♀")
    name = name.replace("Nidoran Male", "Nidoran♂")
    return re.sub(r"^Basic (\w+ Energy)$", r"\1", name)


def winners(by_name: dict[str, Counter]) -> dict[str, str]:
    """Local name -> the English name that clearly wins its printings (spellings that
    differ by case only count together; the most frequent one is kept)."""
    found = {}
    for local, counter in by_name.items():
        merged: Counter = Counter()
        spellings: dict[str, Counter] = defaultdict(Counter)
        for english, count in counter.items():
            merged[english.casefold()] += count
            spellings[english.casefold()][english] += count
        key, count = merged.most_common(1)[0]
        if count >= MAJORITY * sum(merged.values()):
            found[local] = spellings[key].most_common(1)[0][0]
    return found


def main() -> None:
    printings, signatures, fingerprints = local_names()
    skipped = renumbered(signatures)
    ratios = length_ratios(signatures)
    print(f"own numbering: {len(skipped)} Korean / Chinese sets, text lengths {ratios}")

    def usable(printing: tuple[str, str], lang: str) -> bool:
        return (printing[0], lang) not in skipped and same_card(signatures[printing], lang, ratios)

    codes = {code for code, _ in printings}
    print(f"dataset: {len(printings)} printings, {len(codes)} set codes")
    sets = expansions(wikitext(EXPANSIONS) or "")
    pages: dict[str, str | None] = {}
    votes: dict[str, dict[str, Counter]] = {lang: defaultdict(Counter) for lang in FOLDERS.values()}
    matched, missing, mismatched = 0, [], []
    for code, page, title in sets:
        if code.casefold() not in codes:
            continue
        if page not in pages:
            pages[page] = wikitext(f"{page} (TCG)")
        text = pages[page]
        english = english_names(set_list(text or "", title))
        if not english:
            missing.append(f"{code} ({title})")
            continue
        langs = {lang for lang in FOLDERS.values() if agrees(english, printings, code, lang)}
        if not langs:
            mismatched.append(f"{code} ({title})")
            continue
        matched += 1
        for number, name in english.items():
            printing = (code.casefold(), number)
            for lang, local in printings.get(printing, {}).items():
                if lang in langs and usable(printing, lang):
                    votes[lang][normalize_name(local)][english_form(name)] += 1
    print(f"Bulbapedia: {len(sets)} expansions listed, {matched} set lists joined")
    if missing:
        print("no set list:", ", ".join(missing))
    if mismatched:
        print("other numbering (skipped):", ", ".join(mismatched))

    # Japanese names now known name the Korean and Chinese printings of the same card
    # (same code, number and illustrator) in every set, listed by Bulbapedia or not.
    items = item_names()
    card_names = {
        lang: {normalize_name(by[lang]) for by in printings.values() if lang in by}
        for lang in FOLDERS.values()
    }
    japanese = with_items(winners(votes["ja"]), card_names["ja"], items["ja"])
    aliases = japanese_sets(signatures, skipped)
    trainers: dict[str, list[tuple[tuple, str]]] = defaultdict(list)
    for (code, number), by_lang in signatures.items():
        sig, ja_name = by_lang.get("ja"), printings[(code, number)].get("ja")
        if sig and not sig[1] and ja_name:
            trainers[code].append((sig, ja_name))

    def trainer_match(code: str, sig: tuple, lang: str) -> str | None:
        found = {
            japanese.get(normalize_name(ja_name))
            for other, ja_name in trainers.get(code, [])
            if same_card({"ja": other, lang: sig}, lang, ratios)
        }
        return found.pop() if len(found) == 1 else None

    print(f"Korean / Chinese sets matched to a Japanese set of another code: {len(aliases)}")
    for printing, local in printings.items():
        for lang, name in local.items():
            if lang == "ja":
                continue
            source = printing
            if (printing[0], lang) in aliases:
                source = (aliases[(printing[0], lang)], printing[1])
            elif (printing[0], lang) in skipped:
                continue
            other = signatures.get(source, {}).get("ja")
            english = japanese.get(normalize_name(printings.get(source, {}).get("ja", "")))
            pair = {"ja": other, lang: signatures[printing][lang]}
            if other and english and same_card(pair, lang, ratios):
                votes[lang][normalize_name(name)][english] += 1
            elif not signatures[printing][lang][1]:
                # Trainers: Korean sets often order them their own way. The one Japanese
                # Trainer of the set with the same signature is the card.
                english = trainer_match(source[0], signatures[printing][lang], lang)
                if english:
                    votes[lang][normalize_name(name)][english] += 1

    # Pokémon: the fingerprint names the English card ("다투곰 붉은 달 ex" = "Bloodmoon
    # Ursaluna ex"), when it names one English card only (not Unown A to Z).
    for by_lang in fingerprints.values():
        english = by_lang.get("en")
        if not english or len(english) != 1:
            continue
        name = english_form(next(iter(english)))
        for lang, local in by_lang.items():
            if lang != "en" and len(local) == 1:
                votes[lang][next(iter(local))][name] += 1

    table: dict[str, dict[str, str]] = {}
    for lang, by_name in votes.items():
        found = with_items(winners(by_name), card_names[lang], items[lang])
        # Names species or the Basic Energy words already translate stay out.
        kept = {
            local: english
            for local, english in found.items()
            if derive_names(local, lang, []).get("en") != english and not basic_energy(local)
        }
        table[lang] = dict(sorted(kept.items()))
        if DEBUG:
            for local in sorted(set(by_name) - set(found))[:DEBUG]:
                print("  ambiguous", lang, local, by_name[local].most_common(3))
        ambiguous = len(set(by_name) - set(found))
        print(f"{lang}: {len(kept)} names, {ambiguous} ambiguous dropped")
    TARGET.write_text(json.dumps(table, ensure_ascii=False, indent=0, sort_keys=True) + "\n")
    print(f"wrote {TARGET}")


if __name__ == "__main__":
    main()
