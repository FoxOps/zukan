"""Split of the Pokémon and Yu-Gi-Oh! games by market (0.17.0), run by a database
migration on the stored catalog, with no download:

- sets of the Asian and Chinese markets move to their game (`pokemon-asia`,
  `pokemon-china`, `yugioh-ocg`) with their printings, which keep their ids: owned
  copies, prices, price history and manual prices stay where they are;
- cards follow their printings (a card printed in both markets becomes one card in each
  game, names copied);
- printings that held languages of another market (Simplified Chinese on Japanese
  printings, Korean and Chinese on Yu-Gi-Oh! TCG printings) give them, and the copies in
  them, to a printing of the other game under the id its next sync gives it;
- cached pictures of the moved sets move to the new game's folder.

The next catalog sync of each game (forced by its `catalog_version`) fills the rest, and
`catalog.adopt_orphans` moves copies left on a printing whose id it guessed wrong.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.services import layout

NEW_GAMES = {
    "pokemon-asia": "Pokémon TCG Asia",
    "pokemon-china": "Pokémon TCG China",
    "yugioh-ocg": "Yu-Gi-Oh! OCG",
}
# (game, new game, languages of the sets that move).
SET_MOVES = [
    ("pokemon", "pokemon-asia", ("ja", "ko", "zh-hant", "th", "id")),
    ("pokemon", "pokemon-china", ("zh-hans",)),
    ("yugioh", "yugioh-ocg", ("ja", "ko", "zh-hans", "zh-hant")),
]
# Languages each game's cards are named in (Yu-Gi-Oh! cards had every language).
YUGIOH_NAMES = {
    "yugioh": ("en", "fr", "de", "it", "pt", "es"),
    "yugioh-ocg": ("ja", "ko", "zh-hans", "zh-hant", "en"),
}


@dataclass
class SplitReport:
    sets: dict[str, int] = field(default_factory=dict)
    # Printings that gave languages to the other game, and copies that moved with them.
    split_printings: int = 0
    moved_items: int = 0
    files: int = 0


def _rows(conn: Connection, sql: str, **params):
    return conn.execute(sa.text(sql), params).all()


def _scalar(conn: Connection, sql: str, **params):
    return conn.execute(sa.text(sql), params).scalar()


def _ygo_tag(rarity: str | None) -> str:
    """`yugioh.codes.tag`, kept here so the migration does not change with it."""
    return re.sub(r"[^a-z0-9]", "", (rarity or "").casefold()) or "none"


def _target_card(conn: Connection, card_id: int, game: str) -> int:
    """The card of `game` with the external id of `card_id`, copied (with its card-level
    names) when missing."""
    found = _scalar(
        conn,
        "SELECT t.id FROM card t JOIN card c ON c.external_id = t.external_id "
        "WHERE c.id = :card AND t.game_id = :game",
        card=card_id,
        game=game,
    )
    if found is not None:
        return found
    new_id = _scalar(
        conn,
        "INSERT INTO card (game_id, external_id, name, colors, attributes, last_seen_at) "
        "SELECT :game, external_id, name, colors, attributes, last_seen_at FROM card "
        "WHERE id = :card RETURNING id",
        card=card_id,
        game=game,
    )
    conn.execute(
        sa.text(
            "INSERT INTO card_name (card_id, printing_id, lang, name) "
            "SELECT :new, NULL, lang, name FROM card_name "
            "WHERE card_id = :card AND printing_id IS NULL ON CONFLICT DO NOTHING"
        ),
        {"new": new_id, "card": card_id},
    )
    return new_id


def _move_printing_card(conn: Connection, printing_id: int, card_id: int, game: str) -> None:
    """Put the printing (and its printed names) on the card of `game`."""
    target = _target_card(conn, card_id, game)
    if target == card_id:
        return
    conn.execute(
        sa.text("UPDATE printing SET card_id = :t WHERE id = :p"), {"t": target, "p": printing_id}
    )
    conn.execute(
        sa.text("UPDATE card_name SET card_id = :t WHERE printing_id = :p"),
        {"t": target, "p": printing_id},
    )


def _drop_empty_cards(conn: Connection, game: str) -> None:
    conn.execute(
        sa.text(
            "DELETE FROM card c WHERE c.game_id = :game "
            "AND NOT EXISTS (SELECT 1 FROM printing p WHERE p.card_id = c.id)"
        ),
        {"game": game},
    )


def _move_items(conn: Connection, from_id: int, to_id: int, lang: str | None = None) -> int:
    """Copies of a printing (of one language) onto another, merged with the same copy
    there (quantities added, history kept). Returns how many lines moved."""
    where = "printing_id = :src" + (" AND language = :lang" if lang else "")
    items = _rows(
        conn,
        f"SELECT id, user_id, finish, condition, language, quantity, manual_price, notes "
        f"FROM collection_item WHERE {where}",
        src=from_id,
        lang=lang,
    )
    for item in items:
        same = _rows(
            conn,
            "SELECT id FROM collection_item WHERE user_id = :u AND printing_id = :p "
            "AND finish = :f AND condition = :c AND language = :l",
            u=item.user_id,
            p=to_id,
            f=item.finish,
            c=item.condition,
            l=item.language,
        )
        if not same:
            conn.execute(
                sa.text("UPDATE collection_item SET printing_id = :p WHERE id = :id"),
                {"p": to_id, "id": item.id},
            )
            continue
        conn.execute(
            sa.text(
                "UPDATE collection_item SET quantity = quantity + :q, "
                "manual_price = coalesce(manual_price, :price), notes = coalesce(notes, :notes) "
                "WHERE id = :id"
            ),
            {"q": item.quantity, "price": item.manual_price, "notes": item.notes, "id": same[0].id},
        )
        conn.execute(
            sa.text("UPDATE stock_transaction SET item_id = :to WHERE item_id = :id"),
            {"to": same[0].id, "id": item.id},
        )
        conn.execute(sa.text("DELETE FROM collection_item WHERE id = :id"), {"id": item.id})
    return len(items)


def _move_sets(conn: Connection, report: SplitReport) -> dict[tuple[str, str], list[int]]:
    moved: dict[tuple[str, str], list[int]] = {}
    for old, new, langs in SET_MOVES:
        set_ids = [
            r.id
            for r in _rows(
                conn,
                "SELECT id FROM card_set WHERE game_id = :old AND lang = ANY(:langs)",
                old=old,
                langs=list(langs),
            )
        ]
        moved[(old, new)] = set_ids
        report.sets[new] = len(set_ids)
        if not set_ids:
            continue
        conn.execute(
            sa.text("UPDATE card_set SET game_id = :new WHERE id = ANY(:ids)"),
            {"new": new, "ids": set_ids},
        )
        for printing_id, card_id in _rows(
            conn, "SELECT id, card_id FROM printing WHERE set_id = ANY(:ids)", ids=set_ids
        ):
            _move_printing_card(conn, printing_id, card_id, new)
        # Cross-check differences and gap checks of those sets are the new game's.
        conn.execute(
            sa.text("UPDATE catalog_discrepancy SET game_id = :new WHERE set_id = ANY(:ids)"),
            {"new": new, "ids": set_ids},
        )
        conn.execute(
            sa.text(
                "UPDATE gap_check g SET game_id = :new FROM card_set s "
                "WHERE s.id = ANY(:ids) AND g.game_id = :old AND g.set_external_id = s.external_id"
            ),
            {"new": new, "old": old, "ids": set_ids},
        )
    for old, _, _ in SET_MOVES:
        _drop_empty_cards(conn, old)
    return moved


def _ensure_set(conn: Connection, game: str, external_id: str, code: str, name: str, lang: str):
    conn.execute(
        sa.text(
            "INSERT INTO card_set (game_id, external_id, code, name, lang) "
            "VALUES (:game, :ext, :code, :name, :lang) ON CONFLICT DO NOTHING"
        ),
        {"game": game, "ext": external_id, "code": code, "name": name, "lang": lang},
    )
    return _scalar(
        conn,
        "SELECT id FROM card_set WHERE game_id = :game AND external_id = :ext",
        game=game,
        ext=external_id,
    )


def _give_language(
    conn: Connection,
    printing,
    lang: str,
    game: str,
    set_id: int,
    external_id: str,
    number: str,
    report: SplitReport,
) -> None:
    """Make `printing`'s language `lang` a printing of `game` (in set `set_id`)."""
    image = (printing.image_urls or {}).get(lang)
    conn.execute(
        sa.text(
            "INSERT INTO printing (card_id, set_id, external_id, collector_number, rarity, "
            "artist, finishes, languages, image_urls, attributes) "
            "VALUES (:card, :set, :ext, :number, :rarity, :artist, :finishes, :langs, "
            "CAST(:images AS jsonb), CAST(:attributes AS jsonb)) ON CONFLICT DO NOTHING"
        ),
        {
            "card": _target_card(conn, printing.card_id, game),
            "set": set_id,
            "ext": external_id,
            "number": number,
            "rarity": printing.rarity,
            "artist": printing.artist,
            "finishes": list(printing.finishes or []),
            "langs": [lang],
            "images": _json({lang: image} if image else {}),
            "attributes": _json({"split_from": printing.id}),
        },
    )
    new_id = _scalar(
        conn,
        "SELECT id FROM printing WHERE set_id = :set AND external_id = :ext",
        set=set_id,
        ext=external_id,
    )
    if new_id is None or new_id == printing.id:
        return
    conn.execute(
        sa.text(
            "UPDATE printing SET languages = array_append(languages, :lang) "
            "WHERE id = :id AND NOT (:lang = ANY(languages))"
        ),
        {"lang": lang, "id": new_id},
    )
    report.moved_items += _move_items(conn, printing.id, new_id, lang)
    new_card = _scalar(conn, "SELECT card_id FROM printing WHERE id = :id", id=new_id)
    conn.execute(
        sa.text(
            "UPDATE card_name SET printing_id = :new, card_id = :card "
            "WHERE printing_id = :old AND lang = :lang"
        ),
        {"new": new_id, "card": new_card, "old": printing.id, "lang": lang},
    )
    conn.execute(
        sa.text(
            "UPDATE printing SET languages = array_remove(languages, :lang), "
            "image_urls = image_urls - :lang, image_paths = image_paths - :lang, "
            "attributes = attributes #- ARRAY['numbers', :lang] WHERE id = :id"
        ),
        {"lang": lang, "id": printing.id},
    )
    report.split_printings += 1


def _json(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


_PRINTING = (
    "SELECT p.id, p.card_id, p.external_id, p.collector_number, p.rarity, p.artist, "
    "p.finishes, p.languages, p.image_urls, p.attributes, s.external_id AS set_ext, "
    "s.code AS set_code, s.name AS set_name FROM printing p JOIN card_set s ON s.id = p.set_id "
)


def _split_yugioh(conn: Connection, report: SplitReport) -> None:
    """Korean and Chinese languages of TCG printings (`attributes.numbers`): printings of
    the OCG set of their code ("BETB-KR024" in "BETB-KR")."""
    asian = ("ko", "zh-hans", "zh-hant")
    for printing in _rows(
        conn,
        _PRINTING + "WHERE s.game_id = 'yugioh' AND p.languages && CAST(:langs AS varchar[])",
        langs=list(asian),
    ):
        numbers = (printing.attributes or {}).get("numbers") or {}
        for lang in asian:
            number = numbers.get(lang)
            if lang not in printing.languages or not number:
                continue
            prefix = number.rstrip("0123456789") or number
            set_id = _ensure_set(conn, "yugioh-ocg", prefix, prefix, printing.set_name, lang)
            external_id = f"{number}~{_ygo_tag(printing.rarity)}"
            _give_language(conn, printing, lang, "yugioh-ocg", set_id, external_id, number, report)


def _split_pokemon(conn: Connection, report: SplitReport) -> None:
    """Simplified Chinese on printings of Asian sets (a mainland set of the same code
    joined them): printings of a China set of that id."""
    for printing in _rows(
        conn, _PRINTING + "WHERE s.game_id = 'pokemon-asia' AND 'zh-hans' = ANY(p.languages)"
    ):
        code = printing.set_ext.removeprefix("asia:")
        set_id = _ensure_set(
            conn, "pokemon-china", printing.set_ext, code, printing.set_name, "zh-hans"
        )
        _give_language(
            conn,
            printing,
            "zh-hans",
            "pokemon-china",
            set_id,
            printing.external_id,
            printing.collector_number or printing.external_id,
            report,
        )
    for old in ("yugioh", "pokemon-asia"):
        _drop_empty_cards(conn, old)


def _yugioh_names(conn: Connection) -> None:
    """Yu-Gi-Oh! cards named in their game's languages only."""
    for game, langs in YUGIOH_NAMES.items():
        conn.execute(
            sa.text(
                "DELETE FROM card_name n USING card c WHERE n.card_id = c.id "
                "AND c.game_id = :game AND n.printing_id IS NULL AND NOT (n.lang = ANY(:langs))"
            ),
            {"game": game, "langs": list(langs)},
        )


def _settings(conn: Connection) -> None:
    """People's chosen catalog games and the admins' field rules cover the new games."""
    for old, new, _ in SET_MOVES:
        conn.execute(
            sa.text(
                'UPDATE "user" SET catalog_games = array_append(catalog_games, :new) '
                "WHERE :old = ANY(catalog_games) AND NOT (:new = ANY(catalog_games))"
            ),
            {"old": old, "new": new},
        )
        conn.execute(
            sa.text(
                "INSERT INTO catalog_field_rule (game_id, source, field, prefer, created_by, "
                "created_at) SELECT :new, source, field, prefer, created_by, created_at "
                "FROM catalog_field_rule WHERE game_id = :old ON CONFLICT DO NOTHING"
            ),
            {"old": old, "new": new},
        )


def _move_files(conn: Connection, root: Path, moved: dict[tuple[str, str], list[int]]) -> int:
    """Card pictures (`<game>/cards/<set id>/`) and set icons (`<game>/sets/<set id>.*`)
    of the moved sets, to the new game's folders; stored card paths follow. Idempotent."""
    files = 0
    for (old, new), set_ids in moved.items():
        for set_id in set_ids:
            source = layout.game_folder(root, old, layout.CARDS) / str(set_id)
            if source.is_dir():
                files += layout._merge_move(
                    source, layout.game_folder(root, new, layout.CARDS) / str(set_id)
                )
            icons = layout.game_folder(root, old, layout.SETS)
            for icon in icons.glob(f"{set_id}.*") if icons.is_dir() else []:
                target = layout.game_folder(root, new, layout.SETS) / icon.name
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(icon, target)
                files += 1
        if set_ids:
            conn.execute(
                sa.text(
                    "UPDATE printing SET image_paths = ("
                    "  SELECT jsonb_object_agg(e.key, regexp_replace(e.value, :pattern, :new))"
                    "  FROM jsonb_each_text(printing.image_paths) AS e) "
                    "WHERE set_id = ANY(:ids) AND image_paths <> '{}'::jsonb"
                ),
                {"pattern": f"^{re.escape(old)}/", "new": f"{new}/", "ids": set_ids},
            )
    return files


def split_games(conn: Connection, image_root: Path) -> SplitReport:
    report = SplitReport()
    for game_id, name in NEW_GAMES.items():
        conn.execute(
            sa.text("INSERT INTO game (id, name) VALUES (:id, :name) ON CONFLICT DO NOTHING"),
            {"id": game_id, "name": name},
        )
    moved = _move_sets(conn, report)
    _split_yugioh(conn, report)
    _split_pokemon(conn, report)
    _yugioh_names(conn)
    _settings(conn)
    report.files = _move_files(conn, image_root, moved)
    return report
