"""The 0.17.0 split of the Pokémon and Yu-Gi-Oh! games, on a catalog stored before it."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.main import register_games
from app.models import (
    Card,
    CardName,
    CardSet,
    CatalogDiscrepancy,
    CollectionItem,
    PriceSnapshot,
    Printing,
    StockTransaction,
    User,
)
from app.services import layout
from app.services.split import split_games
from tests.conftest import make_user


@pytest.fixture
def image_root(monkeypatch, tmp_path):
    root = tmp_path / "images"
    monkeypatch.setattr(get_settings(), "image_dir", root)
    return root


async def _set(session, game, external_id, code, lang):
    card_set = CardSet(
        game_id=game, external_id=external_id, code=code, name=external_id, lang=lang
    )
    session.add(card_set)
    await session.flush()
    return card_set


async def _card(session, game, external_id, names):
    card = Card(game_id=game, external_id=external_id, name=external_id, colors=[], attributes={})
    session.add(card)
    await session.flush()
    session.add_all(CardName(card_id=card.id, lang=lang, name=name) for lang, name in names.items())
    return card


async def _printing(session, card, card_set, external_id, languages, **fields):
    printing = Printing(
        card_id=card.id,
        set_id=card_set.id,
        external_id=external_id,
        collector_number=fields.pop("collector_number", external_id),
        finishes=fields.pop("finishes", ["normal"]),
        languages=languages,
        image_urls=fields.pop("image_urls", {}),
        image_paths=fields.pop("image_paths", {}),
        attributes=fields.pop("attributes", {}),
        **fields,
    )
    session.add(printing)
    await session.flush()
    return printing


async def _own(session, user, printing, language, quantity, finish="normal", **fields):
    item = CollectionItem(
        user_id=user.id,
        printing_id=printing.id,
        finish=finish,
        condition="NM",
        language=language,
        quantity=quantity,
        **fields,
    )
    session.add(item)
    await session.flush()
    session.add(StockTransaction(user_id=user.id, item_id=item.id, delta=quantity, source="web"))
    return item


async def test_split_keeps_every_owned_copy(session, image_root):
    await register_games()
    user = await make_user(session)
    user.catalog_games = ["pokemon", "yugioh", "mtg"]

    # Pokémon: an international set, a Japanese one (Simplified Chinese joined it), a
    # Korean-only one and a mainland Chinese one.
    swsh3 = await _set(session, "pokemon", "swsh3", "DAA", None)
    sv1a = await _set(session, "pokemon", "SV1a", "SV1a", "ja")
    m2 = await _set(session, "pokemon", "M2", "M2", "ko")
    cs = await _set(session, "pokemon", "151C", "151C", "zh-hans")
    furret = await _card(session, "pokemon", "en:furret", {"en": "Furret", "ja": "オオタチ"})
    tropius = await _card(session, "pokemon", "ja:トロピウス", {"ja": "トロピウス"})
    pikachu = await _card(session, "pokemon", "en:pikachu", {"en": "Pikachu"})
    furret_en = await _printing(session, furret, swsh3, "136", ["en", "fr"])
    furret_ja = await _printing(
        session,
        furret,
        sv1a,
        "002",
        ["ja"],
        image_urls={"ja": "https://img/ja.webp"},
        image_paths={"ja": f"pokemon/cards/{sv1a.id}/x-ja.webp"},
    )
    tropius_p = await _printing(
        session,
        tropius,
        sv1a,
        "001",
        ["ja", "zh-hans"],
        image_urls={"ja": "https://img/1-ja.webp", "zh-hans": "https://img/1-zh.png"},
    )
    session.add(
        CardName(card_id=tropius.id, printing_id=tropius_p.id, lang="zh-hans", name="热带龙")
    )
    await _printing(session, pikachu, m2, "050", ["ko"])
    await _printing(session, pikachu, cs, "025", ["zh-hans"])

    # Yu-Gi-Oh!: a TCG printing that had Korean as a language, a Japanese (OCG) set.
    mp25 = await _set(session, "yugioh", "2025 Mega-Pack Tin", "MP25", "en")
    be1 = await _set(session, "yugioh", "BE1-JP", "BE1-JP", "ja")
    pot = await _card(
        session,
        "yugioh",
        "55144522",
        {"en": "Pot of Greed", "fr": "Pot de Cupidité", "ko": "욕망의 항아리"},
    )
    pot_tcg = await _printing(
        session,
        pot,
        mp25,
        "MP25-EN050~starlightrare",
        ["en", "fr", "ko"],
        collector_number="MP25-EN050",
        rarity="Starlight Rare",
        finishes=["first"],
        attributes={"numbers": {"ko": "MP25-KR050"}},
        image_urls={"en": "https://img/en.jpg", "ko": "https://img/MP25-KR050.png"},
    )
    # A Korean rarity the TCG set lacks: a printing of its own there, Korean only.
    korean_only = await _printing(
        session,
        pot,
        mp25,
        "MP25-KR050~secretrare",
        ["ko"],
        collector_number="MP25-KR050",
        rarity="Secret Rare",
        attributes={"numbers": {"ko": "MP25-KR050"}},
    )
    pot_jp = await _printing(
        session, pot, be1, "BE1-JP001~ultrarare", ["ja"], collector_number="BE1-JP001"
    )

    owned = [
        await _own(session, user, furret_en, "en", 2),
        await _own(session, user, furret_ja, "ja", 1, manual_price=Decimal("4.50")),
        await _own(session, user, tropius_p, "ja", 1),
        await _own(session, user, tropius_p, "zh-hans", 3),
        await _own(session, user, pot_tcg, "en", 1, "first"),
        await _own(session, user, pot_tcg, "ko", 2, "first"),
        await _own(session, user, pot_jp, "ja", 1),
    ]
    session.add(
        PriceSnapshot(
            printing_id=furret_ja.id,
            finish="normal",
            date=date(2026, 10, 1),
            trend=Decimal("1"),
            source="cardmarket",
        )
    )
    session.add(
        CatalogDiscrepancy(
            game_id="pokemon",
            source="x",
            set_id=sv1a.id,
            field="name",
            primary_value="a",
            secondary_value="b",
        )
    )
    await session.commit()
    picture = image_root / "pokemon" / "cards" / str(sv1a.id) / "x-ja.webp"
    picture.parent.mkdir(parents=True)
    picture.write_bytes(b"img")
    icon = image_root / "pokemon" / "sets" / f"{sv1a.id}.png"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"icon")
    total = await session.scalar(select(func.sum(CollectionItem.quantity)))

    async with session.bind.connect() as conn:
        report = await conn.run_sync(lambda c: split_games(c, image_root))
        await conn.commit()
    session.expunge_all()

    sets = set((await session.execute(select(CardSet.game_id, CardSet.external_id))).all())
    assert sets == {
        ("pokemon", "swsh3"),
        ("pokemon-asia", "SV1a"),
        ("pokemon-asia", "M2"),
        ("pokemon-china", "151C"),
        # The Simplified Chinese printings of SV1a, in a set of the China game.
        ("pokemon-china", "SV1a"),
        ("yugioh", "2025 Mega-Pack Tin"),
        ("yugioh-ocg", "BE1-JP"),
        ("yugioh-ocg", "MP25-KR"),
    }
    assert report.sets == {"pokemon-asia": 2, "pokemon-china": 1, "yugioh-ocg": 1}

    # Nothing owned is lost; moved printings keep their ids, so copies stay on them.
    assert await session.scalar(select(func.sum(CollectionItem.quantity))) == total
    items = {i.id: i for i in await session.scalars(select(CollectionItem))}
    assert items[owned[1].id].printing_id == furret_ja.id
    assert items[owned[1].id].manual_price == Decimal("4.50")
    assert await session.scalar(select(func.count()).select_from(StockTransaction)) == len(owned)

    async def game_of(printing_id):
        return await session.scalar(
            select(CardSet.game_id).join(Printing).where(Printing.id == printing_id)
        )

    # Cards follow their printings: Furret is a card of each game.
    furret_ja_card = await session.get(Card, (await session.get(Printing, furret_ja.id)).card_id)
    assert (furret_ja_card.game_id, furret_ja_card.external_id) == ("pokemon-asia", "en:furret")
    names = set(
        await session.scalars(select(CardName.name).where(CardName.card_id == furret_ja_card.id))
    )
    assert names == {"Furret", "オオタチ"}
    assert (await session.get(Card, furret.id)).game_id == "pokemon"
    # Prices stay with the printing.
    assert (
        await session.scalar(
            select(func.count())
            .select_from(PriceSnapshot)
            .where(PriceSnapshot.printing_id == furret_ja.id)
        )
        == 1
    )
    discrepancy = await session.scalar(select(CatalogDiscrepancy))
    assert discrepancy.game_id == "pokemon-asia"

    # Simplified Chinese left the Japanese printing for a China one, with its copies.
    japanese = await session.get(Printing, tropius_p.id)
    assert japanese.languages == ["ja"] and set(japanese.image_urls) == {"ja"}
    chinese_item = items[owned[3].id]
    assert await game_of(chinese_item.printing_id) == "pokemon-china"
    chinese = await session.get(Printing, chinese_item.printing_id)
    assert (chinese.external_id, chinese.languages) == ("001", ["zh-hans"])
    assert chinese.image_urls == {"zh-hans": "https://img/1-zh.png"}
    assert (
        await session.scalar(select(CardName.name).where(CardName.printing_id == chinese.id))
        == "热带龙"
    )
    assert items[owned[2].id].printing_id == tropius_p.id

    # Korean left the TCG printing for the OCG set of its code.
    korean_item = items[owned[5].id]
    korean = await session.get(Printing, korean_item.printing_id)
    assert (korean.external_id, korean.collector_number, korean.languages) == (
        "MP25-KR050~starlightrare",
        "MP25-KR050",
        ["ko"],
    )
    assert await game_of(korean.id) == "yugioh-ocg" and korean.finishes == ["first"]
    tcg = await session.get(Printing, pot_tcg.id)
    assert tcg.languages == ["en", "fr"] and not tcg.attributes.get("numbers")
    assert set(tcg.image_urls) == {"en"}
    assert items[owned[4].id].printing_id == pot_tcg.id
    # The Korean-only printing left the TCG set for the OCG one: no empty printing stays.
    assert await session.get(Printing, korean_only.id) is None
    ocg_ids = set(
        await session.scalars(
            select(Printing.external_id).join(CardSet).where(CardSet.external_id == "MP25-KR")
        )
    )
    assert ocg_ids == {"MP25-KR050~starlightrare", "MP25-KR050~secretrare"}
    assert not await session.scalar(select(func.count()).where(Printing.languages == []))
    # Yu-Gi-Oh! cards are named in their game's languages.
    tcg_names = set(await session.scalars(select(CardName.lang).where(CardName.card_id == pot.id)))
    assert tcg_names == {"en", "fr"}
    ocg_card = (await session.get(Printing, pot_jp.id)).card_id
    ocg_names = set(
        await session.scalars(select(CardName.lang).where(CardName.card_id == ocg_card))
    )
    assert ocg_names == {"en", "ko"}

    # Pictures moved with their sets.
    assert not picture.exists() and not icon.exists()
    moved = image_root / "pokemon-asia" / "cards" / str(sv1a.id) / "x-ja.webp"
    assert moved.read_bytes() == b"img"
    assert (layout.game_folder(image_root, "pokemon-asia", layout.SETS) / icon.name).is_file()
    assert (await session.get(Printing, furret_ja.id)).image_paths == {
        "ja": f"pokemon-asia/cards/{sv1a.id}/x-ja.webp"
    }
    user = await session.get(User, user.id)
    assert user.catalog_games == [
        "pokemon",
        "yugioh",
        "mtg",
        "pokemon-asia",
        "pokemon-china",
        "yugioh-ocg",
    ]

    # Run twice (an interrupted migration): nothing changes.
    async with session.bind.connect() as conn:
        again = await conn.run_sync(lambda c: split_games(c, image_root))
        await conn.commit()
    assert again.sets == {"pokemon-asia": 0, "pokemon-china": 0, "yugioh-ocg": 0}
    assert again.split_printings == 0


async def test_sync_adopts_copies_of_printings_under_old_ids(session):
    """A printing the split guessed another id for: the sync's printing of the same set
    code, number and rarity takes its copies."""
    from app.games.base import CardData, CatalogBatch, PrintingData, SetData
    from app.services.catalog import sync_catalog

    await register_games()
    user = await make_user(session)
    old_set = await _set(session, "yugioh-ocg", "MP25-KR", "MP25-KR", "ko")
    card = await _card(session, "yugioh-ocg", "55144522", {"ko": "욕망의 항아리"})
    guessed = await _printing(
        session,
        card,
        old_set,
        "MP25-KR050~starlight",
        ["ko"],
        collector_number="MP25-KR050",
        rarity="Starlight Rare",
    )
    other = await _printing(
        session, card, old_set, "MP25-KR051~ultrarare", ["ko"], collector_number="MP25-KR051"
    )
    await _own(session, user, guessed, "ko", 2)
    await _own(session, user, other, "ko", 1)
    await session.commit()

    class Source:
        id = "yugioh-ocg"
        rarity_in_printing = True

        async def fetch_catalog(self, http):
            printing = PrintingData(
                "MP25-KR050~starlightrare",
                "MP25-KR",
                "MP25-KR050",
                rarity="Starlight Rare",
                languages=["ko"],
            )
            yield CatalogBatch(
                sets=[SetData("MP25-KR", "MP25-KR", "Mega-Pack", "ko")],
                cards=[CardData("55144522", "Pot of Greed", printings=[printing])],
            )

    report = await sync_catalog(session, Source(), None)
    assert report.moved == 1
    session.expunge_all()
    rows = (await session.execute(select(CollectionItem, Printing).join(Printing))).all()
    # The other printing has no match this sync: kept as it is, owned.
    assert {p.external_id: i.quantity for i, p in rows} == {
        "MP25-KR050~starlightrare": 2,
        "MP25-KR051~ultrarare": 1,
    }
    assert await session.get(Printing, guessed.id) is None
