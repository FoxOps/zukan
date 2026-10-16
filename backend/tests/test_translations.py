from sqlalchemy import select

from app.main import register_games
from app.models import Card, CardName
from app.services.translations import fill_translations


async def _card(session, key, category, names):
    card = Card(
        game_id="pokemon", external_id=key, name=key, colors=[], attributes={"category": category}
    )
    session.add(card)
    await session.flush()
    session.add_all(CardName(card_id=card.id, lang=lang, name=name) for lang, name in names.items())
    return card


async def _names(session, card):
    rows = await session.execute(
        select(CardName.lang, CardName.name).where(CardName.card_id == card.id)
    )
    return dict(rows.all())


async def test_latin_names_copied_from_the_card_sharing_a_name(session):
    await register_games()
    await _card(
        session,
        "en:ultra ball",
        "Trainer",
        {"en": "Ultra Ball", "fr": "Hyper Ball", "zh-hant": "高級球", "ja": "ハイパーボール"},
    )
    japanese = await _card(session, "ja:ハイパーボール", "Trainer", {"ja": "ハイパーボール"})
    # Simplified Chinese matches the Traditional spelling.
    chinese = await _card(session, "zh-hans:高级球", "Trainer", {"zh-hans": "高级球"})
    # Two candidates, or another category: left alone.
    await _card(session, "en:switch", "Trainer", {"en": "Switch", "ja": "ポケモンいれかえ"})
    await _card(session, "en:switch 2", "Trainer", {"en": "Switch!", "ja": "ポケモンいれかえ"})
    alone = await _card(session, "ja:ポケモンいれかえ", "Trainer", {"ja": "ポケモンいれかえ"})
    energy = await _card(session, "ja:ハイパーボール energy", "Energy", {"ja": "ハイパーボール"})

    assert await fill_translations(session, "pokemon") == 4
    assert await _names(session, japanese) == {
        "ja": "ハイパーボール",
        "en": "Ultra Ball",
        "fr": "Hyper Ball",
    }
    assert (await _names(session, chinese))["en"] == "Ultra Ball"
    assert await _names(session, alone) == {"ja": "ポケモンいれかえ"}
    assert await _names(session, energy) == {"ja": "ハイパーボール"}
    # Run again (next sync): nothing new.
    assert await fill_translations(session, "pokemon") == 0
