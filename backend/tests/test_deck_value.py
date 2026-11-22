# ruff: noqa: F811 (fixtures imported from test_decks)
"""Decks module: what a deck is worth (allocated copies at their price, the others at the
cheapest printing and finish)."""

from datetime import date
from decimal import Decimal

from app.models import PriceSnapshot, Printing
from tests.test_decks import (  # noqa: F401 (fixtures)
    alice,
    catalog,
    new_deck,
    own,
    put_card,
    put_line,
)
from tests.test_shopping import allocate


async def price(session, printing_id, finish, trend):
    session.add(
        PriceSnapshot(
            printing_id=printing_id,
            finish=finish,
            date=date.today(),
            source="cardmarket",
            trend=Decimal(trend),
        )
    )
    await session.commit()


async def test_deck_value(client, session, alice, catalog):
    bolt, bolt_printing = catalog["Lightning Bolt"]
    elves, elves_printing = catalog["Llanowar Elves"]
    first = await session.get(Printing, bolt_printing)
    reprint = Printing(
        card_id=bolt,
        set_id=first.set_id,
        external_id="bolt-reprint",
        collector_number="99",
        finishes=["nonfoil"],
        languages=["en"],
    )
    session.add(reprint)
    await session.commit()
    await price(session, bolt_printing, "nonfoil", "2.00")
    await price(session, bolt_printing, "foil", "5.00")
    await price(session, reprint.id, "nonfoil", "0.50")

    deck = (await new_deck(client, alice))["deck"]
    await put_card(client, alice, deck["id"], bolt, 4)
    await put_line(client, alice, deck["id"], elves, 2, elves_printing)
    await own(client, alice, bolt_printing, 1, finish="foil")
    await allocate(client, alice, deck["id"], bolt, 1)

    # 1 foil bolt allocated (5.00), 3 more at the reprint's 0.50, no price for the elves.
    expected = {
        "currency": "EUR",
        "allocated": "5.00",
        "rest": "1.50",
        "total": "6.50",
        "unpriced": 2,
    }
    detail = (await client.get(f"/api/decks/{deck['id']}", headers=alice)).json()
    assert detail["deck"]["value"] == expected
    listed = (await client.get("/api/decks", headers=alice)).json()
    assert listed[0]["value"] == expected

    # A line of a printing is priced at that printing, its cheapest finish (removing the
    # card took its allocation back).
    await put_card(client, alice, deck["id"], bolt, 0)
    await put_line(client, alice, deck["id"], bolt, 2, bolt_printing)
    detail = (await client.get(f"/api/decks/{deck['id']}", headers=alice)).json()
    assert (detail["deck"]["value"]["allocated"], detail["deck"]["value"]["rest"]) == ("0", "4.00")
