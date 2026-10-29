from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.core.config import get_settings
from app.games.base import rarity_icon_file, shipped_folders, shipped_rarity_icon
from app.main import register_games
from app.models import Card, CardSet, Printing
from app.services import layout
from app.services.symbols import symbol_file
from tests.conftest import bearer, make_user

OLD = {
    "mtg/12/34-en.jpg": b"card",
    "mtg/12/34-back.png": b"back",
    "pokemon/7/8-ja.webp": b"jp",
    "sets/mtg/12.svg": b"<svg/>",
    "symbols/mtg/W.svg": b"<svg/>",
    "cache/yugioh-konami.json": b"{}",
    "default/mtg/rarity/rare.svg": b"<svg/>",
}
NEW = {
    "mtg/cards/12/34-en.jpg": b"card",
    "mtg/cards/12/34-back.png": b"back",
    "pokemon/cards/7/8-ja.webp": b"jp",
    "mtg/sets/12.svg": b"<svg/>",
    "mtg/symbols/W.svg": b"<svg/>",
    "cache/yugioh-konami.json": b"{}",
    "default/mtg/rarity/rare.svg": b"<svg/>",
}


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def write(root: Path, files: dict[str, bytes]) -> None:
    for name, data in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)


def test_image_folders_move_per_game_and_back(tmp_path):
    write(tmp_path, OLD)
    assert layout.move_to_game_folders(tmp_path) > 0
    assert tree(tmp_path) == NEW
    assert not (tmp_path / "sets").exists() and not (tmp_path / "symbols").exists()
    # Run again (or after an interrupted move): nothing left to do.
    assert layout.move_to_game_folders(tmp_path) == 0
    # A file left in the old place while the new one exists: the new one is kept.
    write(tmp_path, {"mtg/12/34-en.jpg": b"stale"})
    layout.move_to_game_folders(tmp_path)
    assert tree(tmp_path) == NEW
    layout.move_to_old_folders(tmp_path)
    assert tree(tmp_path) == OLD


async def test_stored_card_paths_follow(session):
    await register_games()
    card_set = CardSet(game_id="mtg", external_id="lea", code="LEA", name="Alpha")
    card = Card(game_id="mtg", external_id="bolt", name="Lightning Bolt")
    session.add_all([card_set, card])
    await session.flush()
    session.add(
        Printing(
            card_id=card.id,
            set_id=card_set.id,
            external_id="161",
            image_paths={"en": "mtg/12/34-en.jpg", "fr": "", "de": "mtg/cards/12/34-de.jpg"},
        )
    )
    await session.commit()
    sql = text(layout.REWRITE_PATHS_SQL)
    pattern, replacement = layout.TO_GAME_FOLDERS
    await session.execute(sql.bindparams(pattern=pattern, replacement=replacement))
    await session.commit()
    paths = await session.scalar(select(Printing.image_paths))
    assert paths == {"en": "mtg/cards/12/34-en.jpg", "fr": "", "de": "mtg/cards/12/34-de.jpg"}
    pattern, replacement = layout.TO_OLD_FOLDERS
    await session.execute(sql.bindparams(pattern=pattern, replacement=replacement))
    await session.commit()
    session.expire_all()
    paths = await session.scalar(select(Printing.image_paths))
    assert paths == {"en": "mtg/12/34-en.jpg", "fr": "", "de": "mtg/12/34-de.jpg"}


@pytest.fixture
def image_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "image_dir", tmp_path / "images")
    return tmp_path / "images"


async def test_own_rarity_and_symbol_pictures_win(client, session, image_dir):
    await register_games()
    await make_user(session)
    alice = await bearer(client, "alice")
    shipped = shipped_rarity_icon("yugioh", "secret")
    assert shipped is not None and rarity_icon_file("yugioh", "secret") == shipped
    # Own pictures, named after the rarity / color code.
    own = image_dir / "yugioh" / "rarity" / "secret.png"
    own.parent.mkdir(parents=True)
    own.write_bytes(b"\x89PNG own")
    spell = image_dir / "yugioh" / "symbols" / "spell.svg"
    spell.parent.mkdir(parents=True)
    spell.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    assert rarity_icon_file("yugioh", "secret") == own
    assert symbol_file("yugioh", "spell") == spell

    games = {g["id"]: g for g in (await client.get("/api/games", headers=alice)).json()}
    secret = next(r for r in games["yugioh"]["rarities"] if r["code"] == "secret")
    # The link changes with the file, so browsers do not keep the old picture.
    assert secret["icon"].startswith("/api/games/yugioh/rarities/secret/icon?v=")
    icon = await client.get(secret["icon"], headers=alice)
    assert icon.status_code == 200 and icon.content == b"\x89PNG own"
    assert icon.headers["content-type"] == "image/png"
    # A rarity the game does not have: not served, whatever the folder holds.
    (image_dir / "yugioh" / "rarity" / "nope.png").write_bytes(b"x")
    missing = await client.get("/api/games/yugioh/rarities/nope/icon", headers=alice)
    assert missing.status_code == 404


async def test_rarity_pictures_by_language(client, session, image_dir):
    await register_games()
    await make_user(session)
    alice = await bearer(client, "alice")
    # Japanese and Chinese cards print letters ("RR") where others print stars.
    plain = shipped_rarity_icon("pokemon", "double_rare")
    japanese = shipped_rarity_icon("pokemon", "double_rare", "ja")
    assert plain is not None and plain.name == "double_rare.png"
    assert japanese is not None and japanese.name == "double_rare.ja.png"
    assert rarity_icon_file("pokemon", "double_rare", "zh-hant").name == "double_rare.zh.png"
    assert rarity_icon_file("pokemon", "double_rare", "fr") == plain
    # An own picture of one language wins over the shipped ones.
    own = image_dir / "pokemon" / "rarity" / "double_rare.ja.webp"
    own.parent.mkdir(parents=True)
    own.write_bytes(b"RIFF own")
    assert rarity_icon_file("pokemon", "double_rare", "ja") == own

    games = {g["id"]: g for g in (await client.get("/api/games", headers=alice)).json()}

    def double_rare(game):
        return next(r for r in games[game]["rarities"] if r["code"] == "double_rare")

    # Each game lists its languages' pictograms; the Pokémon games share the pictures.
    assert double_rare("pokemon")["icons"] == {}
    rr = double_rare("pokemon-asia")
    assert set(rr["icons"]) >= {"ja", "zh-hant"}
    assert set(double_rare("pokemon-china")["icons"]) == {"zh-hans"}
    assert rr["icons"]["ja"].startswith(
        "/api/games/pokemon-asia/rarities/double_rare/icon?lang=ja&v="
    )
    icon = await client.get(rr["icons"]["ja"], headers=alice)
    assert icon.status_code == 200 and icon.content == b"RIFF own"
    # A language the game does not have gets the plain pictogram.
    url = "/api/games/pokemon-asia/rarities/double_rare/icon"
    other = await client.get(url, params={"lang": "../ja"}, headers=alice)
    assert other.status_code == 200 and other.content == plain.read_bytes()


def test_own_picture_stays_in_its_folder(image_dir):
    folder = image_dir / "yugioh" / "rarity"
    folder.mkdir(parents=True)
    (folder / "secret.png").write_bytes(b"x")
    (image_dir / "yugioh" / "outside.png").write_bytes(b"x")
    assert layout.own_picture(folder, "secret") == folder / "secret.png"
    for code in ("../outside", "..", "/etc/passwd", "a\\b", ""):
        assert layout.own_picture(folder, code) is None
    # A link leading out of the folder is not followed.
    (folder / "link.png").symlink_to(image_dir / "yugioh" / "outside.png")
    assert layout.own_picture(folder, "link") is None


async def test_shipped_pictures_copied_to_default_folder(image_dir):
    shipped = shipped_folders()
    assert layout.install_defaults(image_dir, shipped) > 0
    rarity = image_dir / "default" / "yugioh" / "rarity"
    symbols = image_dir / "default" / "yugioh" / "symbols"
    assert (rarity / "secret.svg").is_file() and (symbols / "spell.svg").is_file()
    # The copies are served when there is no own picture.
    assert shipped_rarity_icon("yugioh", "secret") == rarity / "secret.svg"
    amber = image_dir / "default" / "lorcana" / "symbols" / "amber.svg"
    assert symbol_file("lorcana", "amber") == amber
    # Nothing to do on the next start; an edited or stray file is put back in line.
    assert layout.install_defaults(image_dir, shipped) == 0
    (rarity / "secret.svg").write_text("edited")
    (rarity / "gone.svg").write_text("old")
    assert layout.install_defaults(image_dir, shipped) == 1
    original = shipped["yugioh"]["rarity"] / "secret.svg"
    assert (rarity / "secret.svg").read_bytes() == original.read_bytes()
    assert not (rarity / "gone.svg").exists()
