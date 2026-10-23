"""Folders of the image directory (`settings.image_dir`), one per game:

    <game>/cards/<set id>/<printing id>-<lang>.<ext>   card pictures (and `-back` faces)
    <game>/sets/<set id>.<ext>                         set icons
    <game>/symbols/<color code>.<svg|png|webp>         color symbols
    <game>/rarity/<rarity code>.<svg|png|webp>         rarity pictograms

    default/<game>/symbols/<color code>.<ext>           pictures shipped with Zukan
    default/<game>/rarity/<rarity code>.<ext>

`<game>` is the game id (mtg, pokemon, pokemon-asia, sorcery, riftbound, yugioh...). The
games of a group (the Pokémon games, the Yu-Gi-Oh! ones) share the symbols and rarity
folders of the group's id (`pokemon/symbols/`). Files put in `<game>/symbols/` and
`<game>/rarity/` by hand win over the ones shipped with Zukan.
`default/` is a copy of the shipped pictures, rewritten on every start (`install_defaults`):
copy one into `<game>/...` to replace it. `cache/` holds source caches (Konami pages).

Before 0.12.0 cards were in `<game>/<set id>/`, set icons in `sets/<game>/` and symbols
in `symbols/<game>/`: `move_to_game_folders` moves them (run by a database migration,
which also rewrites the stored card paths).
"""

import os
import shutil
from pathlib import Path

CARDS = "cards"
SETS = "sets"
SYMBOLS = "symbols"
RARITY = "rarity"
CACHE = "cache"
DEFAULT = "default"
# Top-level folders that are not games.
NOT_GAMES = (SETS, SYMBOLS, CACHE, DEFAULT)
# Pictures people may put in place of the shipped ones.
PICTURE_SUFFIXES = (".svg", ".png", ".webp")


def game_folder(root: Path, game_id: str, kind: str) -> Path:
    return root / game_id / kind


def default_folder(root: Path, game_id: str, kind: str) -> Path:
    return root / DEFAULT / game_id / kind


def own_picture(folder: Path, code: str) -> Path | None:
    """`folder/<code>.<svg|png|webp>`, the first that exists."""
    for suffix in PICTURE_SUFFIXES:
        path = folder / f"{code}{suffix}"
        if path.is_file():
            return path
    return None


def install_defaults(root: Path, shipped: dict[str, dict[str, Path]]) -> int:
    """Copy the shipped pictures (`{game: {kind: package folder}}`) to
    `default/<game>/<kind>/`, replacing changed files and removing ones no longer shipped.
    Returns the number of files written."""
    written = 0
    for game_id, kinds in shipped.items():
        for kind, source in kinds.items():
            files = {f.name: f for f in source.iterdir() if f.suffix in PICTURE_SUFFIXES}
            target = default_folder(root, game_id, kind)
            if not files and not target.is_dir():
                continue
            target.mkdir(parents=True, exist_ok=True)
            for old in target.iterdir():
                if old.is_file() and old.name not in files:
                    old.unlink()
            for name, file in files.items():
                path = target / name
                data = file.read_bytes()
                if path.is_file() and path.read_bytes() == data:
                    continue
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_bytes(data)
                tmp.replace(path)
                written += 1
    return written


def _merge_move(source: Path, target: Path) -> int:
    """Move `source` (a file or folder) to `target`, merging into an existing folder.
    Returns the number of files and folders moved."""
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target)
        return 1
    if source.is_dir() and target.is_dir():
        moved = sum(_merge_move(child, target / child.name) for child in list(source.iterdir()))
        source.rmdir()
        return moved
    # Already there (an earlier, interrupted move): the newer layout wins.
    if source.is_dir():
        shutil.rmtree(source)
    else:
        source.unlink()
    return 0


def move_to_game_folders(root: Path) -> int:
    """Move a pre-0.12.0 image directory to the per-game layout. Idempotent."""
    if not root.is_dir():
        return 0
    moved = 0
    for old, kind in ((SETS, SETS), (SYMBOLS, SYMBOLS)):
        folder = root / old
        if not folder.is_dir():
            continue
        for game in list(folder.iterdir()):
            if game.is_dir():
                moved += _merge_move(game, game_folder(root, game.name, kind))
        if not any(folder.iterdir()):
            folder.rmdir()
    for game in list(root.iterdir()):
        if not game.is_dir() or game.name in NOT_GAMES:
            continue
        for child in list(game.iterdir()):
            # Set folders are database ids.
            if child.is_dir() and child.name.isdigit():
                moved += _merge_move(child, game / CARDS / child.name)
    return moved


# Card paths stored per language in `printing.image_paths` ("" = refused download),
# rewritten when the layout changes (:pattern / :replacement, PostgreSQL regexps).
REWRITE_PATHS_SQL = (
    "UPDATE printing SET image_paths = ("
    "  SELECT jsonb_object_agg(e.key, CASE WHEN e.value ~ :pattern"
    "    THEN regexp_replace(e.value, :pattern, :replacement) ELSE e.value END)"
    "  FROM jsonb_each_text(printing.image_paths) AS e) "
    "WHERE EXISTS (SELECT 1 FROM jsonb_each_text(printing.image_paths) AS e "
    "  WHERE e.value ~ :pattern)"
)
# "mtg/12/345-en.jpg" <-> "mtg/cards/12/345-en.jpg"
TO_GAME_FOLDERS = (r"^([^/]+)/([0-9]+)/", r"\1/cards/\2/")
TO_OLD_FOLDERS = (r"^([^/]+)/cards/([0-9]+)/", r"\1/\2/")


def move_to_old_folders(root: Path) -> int:
    """Back to the pre-0.12.0 layout (database downgrade). Own rarity pictograms stay."""
    if not root.is_dir():
        return 0
    moved = 0
    for game in list(root.iterdir()):
        if not game.is_dir() or game.name in NOT_GAMES:
            continue
        cards = game / CARDS
        for child in list(cards.iterdir()) if cards.is_dir() else []:
            moved += _merge_move(child, game / child.name)
        if cards.is_dir() and not any(cards.iterdir()):
            cards.rmdir()
        for kind in (SETS, SYMBOLS):
            if (game / kind).is_dir():
                moved += _merge_move(game / kind, root / kind / game.name)
    return moved
