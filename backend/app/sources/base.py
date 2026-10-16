"""Generic gap-filling sources: card databases covering several games (tcgcsv, tcg-api.eu,
apitcg), registered under the `zukan.sources` entry point group.

They only fill what a game's own sources left empty — English pictures, rarities,
artists, TCGplayer ids, finishes the provider guessed — and record where they disagree
(name, rarity, rules text). A source fetches only the sets holding such gaps, which keeps
small quotas for what is missing.

Each source lists the games it covers by its own key (TCGplayer category 89, slug
"riftbound"...), mapped to our game ids; a game provider may set `source_keys` to
override that mapping, so a new game needs no change here.
"""

import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from importlib.metadata import entry_points
from typing import Any, Protocol, runtime_checkable

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.db import get_sessionmaker
from app.games.base import (
    CardData,
    CatalogIndex,
    CatalogSource,
    Discrepancy,
    PrintingData,
    SecondaryBatch,
    SetData,
    StoredPrinting,
    compare,
    registry,
)
from app.models import GapCheck

ENTRY_POINT_GROUP = "zukan.sources"


@runtime_checkable
class GapSource(Protocol):
    id: str
    name: str
    # Run order among gap sources: free and unlimited first, small quotas last.
    order: int
    # Their key of each game they cover, by our game id.
    games: dict[str, Any]

    def for_game(self, game_id: str) -> CatalogSource | None:
        """This source bound to one game, None when it does not cover it (or lacks its
        API key)."""
        ...


@lru_cache
def gap_sources() -> list[GapSource]:
    sources = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        source = ep.load()
        if not isinstance(source, GapSource):
            raise TypeError(f"Entry point {ep.name} is not a GapSource")
        sources.append(source)
    return sorted(sources, key=lambda s: (s.order, s.id))


def game_key(source: GapSource, game_id: str) -> Any:
    """The source's key for our game: the provider's `source_keys` first."""
    keys = getattr(registry().get(game_id), "source_keys", None) or {}
    return keys.get(source.id, source.games.get(game_id))


# Gaps of a printing a source can fill.
IMAGE, RARITY, ARTIST, TCGPLAYER, FINISHES = "image", "rarity", "artist", "tcgplayer", "finishes"


def printing_gaps(printing: StoredPrinting) -> set[str]:
    """What an English source may fill on this printing (none for printings that do not
    exist in English)."""
    if printing.languages and "en" not in printing.languages:
        return set()
    gaps = set()
    if "en" not in printing.image_languages:
        gaps.add(IMAGE)
    if not printing.rarity:
        gaps.add(RARITY)
    if not printing.artist:
        gaps.add(ARTIST)
    if not printing.market_ids.get("tcgplayer"):
        gaps.add(TCGPLAYER)
    if printing.finishes_guessed or not printing.finishes:
        gaps.add(FINISHES)
    return gaps


def sets_with_gaps(index: CatalogIndex, wanted: set[str] | None = None) -> dict[str, int]:
    """Number of printings with gaps per set external id; `wanted`: only these gaps."""
    out: dict[str, int] = {}
    for (set_ext, _), printing in index.printings.items():
        gaps = printing_gaps(printing)
        if wanted is not None:
            gaps &= wanted
        if gaps:
            out[set_ext] = out.get(set_ext, 0) + 1
    return out


@dataclass
class ExternalSet:
    key: Any  # the source's id of the set
    name: str
    # Codes the set may go by there (abbreviation, id).
    codes: list[str] = field(default_factory=list)
    release_date: date | None = None


@dataclass
class ExternalPrinting:
    number: str | None
    name: str
    rarity: str | None = None
    artist: str | None = None
    image: str | None = None
    tcgplayer_id: str | None = None
    text: str | None = None
    # Their version names ("Normal", "Holofoil"), turned into our finish codes by
    # `finish_codes`.
    versions: list[str] = field(default_factory=list)


def number_key(value: str | None) -> str:
    """ "001" = "1", "TG05" = "tg5", "131/219" = "131"."""
    value = (value or "").split("/")[0].strip()
    return re.sub(r"(?<![0-9])0+(?=[0-9])", "", value).casefold()


def code_key(value: str) -> str:
    """Set codes written differently by sources: "sv01" = "sv1", "sv03.5" = "sv3pt5"."""
    return number_key(value.replace(".5", "pt5"))


def _name(value: str | None) -> str:
    return (value or "").strip().casefold()


def match_sets(ours: dict[str, SetData], theirs: list[ExternalSet], game_id: str) -> dict[Any, str]:
    """Their set key -> our set external id, for international (or English) sets: by
    code (or a known alias), then name and release date, then name alone."""
    aliases = getattr(registry().get(game_id), "set_aliases", {}) or {}
    candidates = [s for s in ours.values() if s.lang in (None, "en")]
    by_code: dict[str, str] = {}
    for s in candidates:
        for code in (s.code, s.external_id, *aliases.get(s.code, [])):
            by_code.setdefault(code_key(code), s.external_id)
    by_name_date = {(_name(s.name), s.release_date): s.external_id for s in candidates}
    names: dict[str, list[str]] = {}
    for s in candidates:
        names.setdefault(_name(s.name), []).append(s.external_id)
    matches: dict[Any, str] = {}
    used: set[str] = set()
    for raw in theirs:
        found = (
            next((by_code[k] for c in raw.codes if c and (k := code_key(c)) in by_code), None)
            or by_name_date.get((_name(raw.name), raw.release_date))
            or (ids[0] if len(ids := names.get(_name(raw.name), [])) == 1 else None)
        )
        if found and found not in used:
            matches[raw.key] = found
            used.add(found)
    return matches


_SUFFIX = re.compile(r"\s*(\([^)]*\)|-\s*[0-9A-Za-z]*[0-9]+(/[0-9A-Za-z]+)?)\s*$")


# TCGplayer writes Magic rarities as letters (L: basic land, printed common).
_RARITY_LETTERS = {
    "c": "common",
    "u": "uncommon",
    "r": "rare",
    "m": "mythic",
    "l": "common",
    "s": "special",
    "p": "promo",
    "t": "token",
}


# Market categories in the rarity field, not rarities: not compared, never filled.
_NOT_RARITIES = {"promo", "token", "special", "unconfirmed", "code card", "none"}


def rarity_name(value: str | None) -> str | None:
    if value and len(value.strip()) == 1:
        value = _RARITY_LETTERS.get(value.strip().casefold(), value)
    if value and value.strip().casefold() in _NOT_RARITIES:
        return None
    return value


def plain_name(name: str) -> str:
    """Name without the market's version suffixes: "Pikachu - 025/165",
    "Ahri, Alluring (Alternate Art)"."""
    previous = None
    while previous != name:
        previous, name = name, _SUFFIX.sub("", name)
    return name.strip()


def same_name(ours: str, theirs: str) -> bool:
    """Names of one card as two sources write them: a face of a double-faced card
    ("A // B" = "A"), a market's alternate name ("Bag End - Horizon Canopy" = "Horizon
    Canopy"), one with more words ("Lady of Clockwork" = "Orianna, Lady of Clockwork")."""
    mine = [ours, *ours.split(" // ")]
    plain = plain_name(theirs)
    theirs_all = [plain, *plain.split(" - ")]
    return any(
        compare("", None, "", a, b) is None or compare("", None, "", a, b, True) is None
        for a in mine
        for b in theirs_all
        if a.strip() and b.strip()
    )


def pair(
    stored: list[StoredPrinting], theirs: list[ExternalPrinting]
) -> list[tuple[StoredPrinting, ExternalPrinting]]:
    """Their printings of a set paired with ours: TCGplayer id, else number and name."""
    by_tcgplayer = {
        str(p.market_ids["tcgplayer"]): p for p in stored if p.market_ids.get("tcgplayer")
    }
    by_number: dict[str, list[StoredPrinting]] = {}
    for p in stored:
        by_number.setdefault(number_key(p.collector_number or p.external_id), []).append(p)
    out = []
    seen: set[tuple[str, str]] = set()
    for ext in theirs:
        printing = by_tcgplayer.get(str(ext.tcgplayer_id)) if ext.tcgplayer_id else None
        if printing is None:
            # Games without collector numbers (Sorcery): the name, when only one of ours
            # has it. A number alone is not enough: tokens and art cards of a market's
            # set reuse the card numbers.
            same = by_number.get(number_key(ext.number), []) if ext.number else stored
            named = [p for p in same if same_name(p.card_name, ext.name)]
            if len(named) == 1 or (ext.number and named):
                printing = named[0]
        if printing is None:
            continue
        key = (printing.set_external_id, printing.external_id)
        if key in seen:
            continue
        seen.add(key)
        out.append((printing, ext))
    return out


_FINISHES = {
    "normal": ("normal", "nonfoil", "standard"),
    "unlimited": ("normal", "nonfoil", "standard"),
    "foil": ("foil",),
    "holofoil": ("holo", "foil"),
    "unlimited holofoil": ("holo", "foil"),
    "reverse holofoil": ("reverse",),
    "1st edition": ("first_edition",),
    "1st edition normal": ("first_edition",),
    "1st edition holofoil": ("first_edition",),
    "rainbow foil": ("rainbow",),
    "etched": ("etched",),
    "foil etched": ("etched",),
}


def finish_codes(game_id: str, versions: list[str]) -> list[str]:
    """Our finish codes for a market's version names (those the game has)."""
    provider = registry().get(game_id)
    have = [f.code for f in getattr(provider, "finishes", [])]
    out: list[str] = []
    for version in versions:
        code = next((c for c in _FINISHES.get(version.casefold(), ()) if c in have), None)
        if code and code not in out:
            out.append(code)
    return out


_REMINDER = re.compile(r"\([^)]*\)")


def _rules(text: str) -> str:
    return _REMINDER.sub(" ", text)


def fill(
    game_id: str,
    source_id: str,
    printing: StoredPrinting,
    ext: ExternalPrinting,
    check_text: bool = False,
) -> tuple[CardData | None, list[Discrepancy]]:
    """Partial card data with what `ext` has and `printing` lacks, and what they disagree
    on."""
    set_ext, ext_id = printing.set_external_id, printing.external_id
    ext.rarity = rarity_name(ext.rarity)
    checks = [
        None
        if same_name(printing.card_name, ext.name)
        else Discrepancy(set_ext, ext_id, "name", printing.card_name, plain_name(ext.name)),
        compare(set_ext, ext_id, "rarity", printing.rarity, ext.rarity, True),
    ]
    if check_text and printing.card_text and ext.text:
        # Sources write keywords and symbols their own way and some leave out reminder
        # text in parentheses: same words (one may have more) is the same text.
        same = compare(set_ext, ext_id, "text", _rules(printing.card_text), _rules(ext.text), True)
        if same is not None:
            checks.append(Discrepancy(set_ext, ext_id, "text", printing.card_text, ext.text))
    found = [d for d in checks if d is not None]

    gaps = printing_gaps(printing)
    data = PrintingData(external_id=ext_id, set_external_id=set_ext)
    useful = False
    if IMAGE in gaps and ext.image:
        data.images = {"en": ext.image}
        useful = True
    if RARITY in gaps and ext.rarity:
        data.rarity, useful = ext.rarity, True
    if ARTIST in gaps and ext.artist:
        data.artist, useful = ext.artist, True
    if TCGPLAYER in gaps and ext.tcgplayer_id:
        data.attributes["market_ids"] = {"tcgplayer": str(ext.tcgplayer_id)}
        useful = True
    if FINISHES in gaps and (finishes := finish_codes(game_id, ext.versions)):
        data.finishes = [f for f in finishes if f not in printing.finishes]
        # Guessed finishes are now confirmed: no other source is asked again.
        data.attributes["finishes_confirmed"] = source_id
        useful = True
    if not useful:
        return None, found
    card = CardData(
        external_id=printing.card_external_id,
        name=printing.card_name,
        partial=True,
        printings=[data],
    )
    return card, found


def check_set(
    game_id: str,
    source_id: str,
    stored: list[StoredPrinting],
    theirs: list[ExternalPrinting],
    check_text: bool = False,
) -> SecondaryBatch:
    batch = SecondaryBatch(checked_sets=sorted({p.set_external_id for p in stored}))
    for printing, ext in pair(stored, theirs):
        batch.matched += 1
        card, found = fill(game_id, source_id, printing, ext, check_text)
        if card is not None:
            batch.cards.append(card)
        batch.discrepancies += found
    return batch


def stored_by_set(index: CatalogIndex) -> dict[str, list[StoredPrinting]]:
    out: dict[str, list[StoredPrinting]] = {}
    for (set_ext, _), printing in index.printings.items():
        out.setdefault(set_ext, []).append(printing)
    return out


@dataclass
class BoundSource:
    """A gap source for one game, as the catalog job's secondary sources expect."""

    id: str
    name: str
    game_id: str
    run: Callable[[httpx.AsyncClient, CatalogIndex, str], AsyncIterator[SecondaryBatch]]

    # Only sets with gaps are checked: disagreements found elsewhere earlier are kept.
    checks_some_sets = True

    def fetch(self, http: httpx.AsyncClient, index: CatalogIndex) -> AsyncIterator[SecondaryBatch]:
        return self.run(http, index, self.game_id)


# Sets a source with a quota found nothing more for are skipped this long while their
# number of printings with gaps stays the same.
RECHECK_DAYS = 30


async def unchecked(source_id: str, game_id: str, gaps: dict[str, int]) -> dict[str, int]:
    """`gaps` without the sets this source checked recently with as many gaps."""
    async with get_sessionmaker()() as session:
        rows = await session.scalars(
            select(GapCheck).where(GapCheck.source == source_id, GapCheck.game_id == game_id)
        )
        recent = {
            r.set_external_id: r.gaps
            for r in rows
            if r.checked_on > date.today() - timedelta(days=RECHECK_DAYS)
        }
    return {s: n for s, n in gaps.items() if recent.get(s) != n}


async def remember(source_id: str, game_id: str, set_ext: str, gaps: int) -> None:
    async with get_sessionmaker()() as session:
        stmt = insert(GapCheck).values(
            source=source_id,
            game_id=game_id,
            set_external_id=set_ext,
            gaps=gaps,
            checked_on=date.today(),
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["source", "game_id", "set_external_id"],
                set_={"gaps": stmt.excluded.gaps, "checked_on": stmt.excluded.checked_on},
            )
        )
        await session.commit()
