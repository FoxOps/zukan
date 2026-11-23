from app.models import Card, CardSet, Printing
from tests.conftest import bearer, make_user


async def test_previous_and_next_printing_in_set(client, session):
    await make_user(session)
    headers = await bearer(client, "alice")
    card_set = CardSet(game_id="pokemon", external_id="pbl", code="PBL", name="Pitch Black")
    other_set = CardSet(game_id="pokemon", external_id="oth", code="OTH", name="Other")
    session.add_all([card_set, other_set])
    await session.flush()
    printings = {}
    # Collector numbers in printed order, not text order ("41" < "100"); another set's
    # printing between them never shows up.
    for number, name, in_set in [
        ("100", "Secret Mankey", card_set),
        ("42", "Mankey", card_set),
        ("41", "Annihilape", card_set),
        ("43", "Primeape", card_set),
        ("42", "Elsewhere", other_set),
    ]:
        card = Card(game_id="pokemon", external_id=f"{in_set.code}-{number}", name=name)
        session.add(card)
        await session.flush()
        printing = Printing(
            card_id=card.id,
            set_id=in_set.id,
            external_id=f"{in_set.code}-{number}",
            collector_number=number,
            finishes=["normal"],
            languages=["en"],
        )
        session.add(printing)
        await session.flush()
        printings[(in_set.code, number)] = printing
    await session.commit()

    async def neighbors(number: str) -> dict:
        printing_id = printings[("PBL", number)].id
        response = await client.get(f"/api/printings/{printing_id}/neighbors", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    middle = await neighbors("42")
    assert (middle["previous"]["name"], middle["previous"]["collector_number"]) == (
        "Annihilape",
        "41",
    )
    assert (middle["next"]["name"], middle["next"]["collector_number"]) == ("Primeape", "43")
    assert middle["next"]["printing_id"] == printings[("PBL", "43")].id
    assert (await neighbors("41"))["previous"] is None
    last = await neighbors("100")
    assert last["previous"]["collector_number"] == "43"
    assert last["next"] is None

    missing = await client.get("/api/printings/999999/neighbors", headers=headers)
    assert missing.status_code == 404
