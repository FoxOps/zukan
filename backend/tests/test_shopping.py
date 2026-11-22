# ruff: noqa: F811 (fixtures imported from test_decks)
"""Decks module: owned copies on deck summaries, shopping lists of missing cards (files and
lists sent to the Android app)."""

from app.services.decks import line_missing
from tests.conftest import make_user
from tests.test_decks import (  # noqa: F401 (fixtures)
    alice,
    catalog,
    enable,
    own,
    put_card,
    put_line,
)
from tests.test_decks import (
    new_deck as _new_deck,
)


async def allocate(client, headers, deck_id, card_id, quantity):
    response = await client.post(
        f"/api/decks/{deck_id}/allocate",
        json={"card_id": card_id, "quantity": quantity},
        headers=headers,
    )
    assert response.status_code == 200, response.text


async def new_deck(client, headers, name="Burn") -> dict:
    return (await _new_deck(client, headers, name))["deck"]


def test_line_missing():
    # One line of any printing: allocated and free copies cover it.
    assert line_missing([(None, 4)], [1], {}, 3) == [3]
    # A printing's free copies cover its line, others the lines of any printing.
    assert line_missing([(5, 2), (None, 2)], [0, 0], {5: 1, 6: 1}, 2) == [1, 1]
    # Free copies of another printing count for a line of a printing too.
    assert line_missing([(5, 2)], [0], {6: 1}, 1) == [1]
    assert line_missing([(5, 1), (None, 3)], [0, 0], {6: 2}, 2) == [1, 1]


async def test_owned_counts(client, session, alice, catalog):
    bolt, bolt_printing = catalog["Lightning Bolt"]
    mountain, mountain_printing = catalog["Mountain"]
    burn = await new_deck(client, alice)
    other = await new_deck(client, alice, "Other")
    await put_card(client, alice, burn["id"], bolt, 4)
    await put_card(client, alice, burn["id"], mountain, 10)
    await put_card(client, alice, other["id"], bolt, 2)
    await own(client, alice, bolt_printing, 3)
    await own(client, alice, mountain_printing, 12)
    await allocate(client, alice, burn["id"], bolt, 1)
    # The other deck holds 2 of the 3 bolts: Burn has 1 allocated, none free.
    await allocate(client, alice, other["id"], bolt, 2)

    decks = {d["name"]: d for d in (await client.get("/api/decks", headers=alice)).json()}
    assert (decks["Burn"]["copies"], decks["Burn"]["owned"], decks["Burn"]["allocated"]) == (
        14,
        11,
        1,
    )
    assert (decks["Other"]["copies"], decks["Other"]["owned"], decks["Other"]["allocated"]) == (
        2,
        2,
        2,
    )
    detail = (await client.get(f"/api/decks/{burn['id']}", headers=alice)).json()
    assert detail["deck"]["owned"] == 11

    shopping = (await client.get(f"/api/decks/{burn['id']}/shopping", headers=alice)).json()
    assert [(line["name"], line["quantity"]) for line in shopping["lines"]] == [
        ("Lightning Bolt", 3)
    ]


async def test_shopping_files(client, session, alice, catalog):
    elves, elves_printing = catalog["Llanowar Elves"]
    bolt, bolt_printing = catalog["Lightning Bolt"]
    deck = await new_deck(client, alice, "Elves/Bolt")
    await put_line(client, alice, deck["id"], elves, 4, elves_printing)
    await put_card(client, alice, deck["id"], bolt, 2)
    await own(client, alice, bolt_printing, 2)
    await client.patch("/api/auth/me", json={"language": "fr"}, headers=alice)

    url = f"/api/decks/{deck['id']}/shopping/download"
    txt = await client.get(url, headers=alice)
    assert txt.status_code == 200
    assert txt.headers["content-type"].startswith("text/plain")
    assert 'filename="Elves_Bolt.txt"' in txt.headers["content-disposition"]
    assert "Liste d'achats" in txt.text
    assert "[ ][ ][ ][ ] 4 Llanowar Elves (Elfes de Llanowar) · TST 2" in txt.text
    assert "Lightning Bolt" not in txt.text

    md = await client.get(url, params={"format": "md"}, headers=alice)
    assert "- [ ] Llanowar Elves (Elfes de Llanowar) · TST 2 (1/4)" in md.text
    assert "- [ ] Llanowar Elves (Elfes de Llanowar) · TST 2 (4/4)" in md.text

    pdf = await client.get(url, params={"format": "pdf"}, headers=alice)
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    bad = await client.get(url, params={"format": "doc"}, headers=alice)
    assert bad.status_code == 422


async def test_shopping_lists(client, session, alice, catalog):
    bolt, _ = catalog["Lightning Bolt"]
    mountain, _ = catalog["Mountain"]
    deck = await new_deck(client, alice)
    await put_card(client, alice, deck["id"], bolt, 4)
    await put_card(client, alice, deck["id"], mountain, 2)

    sent = await client.post(f"/api/decks/{deck['id']}/shopping-list", headers=alice)
    assert sent.status_code == 201, sent.text
    found = sent.json()
    assert (found["name"], found["copies"], found["bought"]) == ("Burn", 6, 0)
    assert [(i["name"], i["quantity"]) for i in found["items"]] == [
        ("Lightning Bolt", 4),
        ("Mountain", 2),
    ]

    # A copy: changing the deck leaves the list as it was.
    await put_card(client, alice, deck["id"], bolt, 1)
    item = found["items"][0]
    ticked = await client.patch(
        f"/api/shopping-lists/{found['id']}/items/{item['id']}",
        json={"bought": True},
        headers=alice,
    )
    assert ticked.status_code == 200
    assert ticked.json()["bought"] == 4
    assert ticked.json()["items"][0]["quantity"] == 4
    assert (ticked.json()["items"][0]["bought_count"], ticked.json()["items"][0]["bought"]) == (
        4,
        True,
    )

    # One box per copy: 2 of the 4 bought, kept between 0 and the quantity.
    url = f"/api/shopping-lists/{found['id']}/items/{item['id']}"
    half = await client.patch(url, json={"bought_count": 2}, headers=alice)
    assert half.json()["bought"] == 2
    assert (half.json()["items"][0]["bought_count"], half.json()["items"][0]["bought"]) == (
        2,
        False,
    )
    over = await client.patch(url, json={"bought_count": 9}, headers=alice)
    assert over.json()["items"][0]["bought_count"] == 4
    assert (await client.patch(url, json={}, headers=alice)).status_code == 422

    # Another user sees nothing and cannot change or delete it.
    await make_user(session, "bob")
    bob = await enable(client, "bob")
    assert (await client.get("/api/shopping-lists", headers=bob)).json() == []
    assert (await client.get(f"/api/shopping-lists/{found['id']}", headers=bob)).status_code == 404
    assert (
        await client.patch(
            f"/api/shopping-lists/{found['id']}/items/{item['id']}",
            json={"bought": False},
            headers=bob,
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/shopping-lists/{found['id']}", headers=bob)
    ).status_code == 404

    # The list stays when the deck goes.
    assert (await client.delete(f"/api/decks/{deck['id']}", headers=alice)).status_code == 204
    lists = (await client.get("/api/shopping-lists", headers=alice)).json()
    assert [(x["name"], x["deck_id"], x["copies"], x["bought"]) for x in lists] == [
        ("Burn", None, 6, 4)
    ]

    deleted = await client.delete(f"/api/shopping-lists/{found['id']}", headers=alice)
    assert deleted.status_code == 204
    assert (await client.get("/api/shopping-lists", headers=alice)).json() == []


def test_copy_boxes():
    from datetime import date

    from app.services.shopping import ShoppingLine, to_md, to_pdf, to_txt

    lines = [ShoppingLine(1, 2, "Shock", None, "M21", "159", 3, bought=1)]
    day = date(2026, 11, 22)
    assert "[x][ ][ ] 3 Shock · M21 159" in to_txt("Burn", lines, "en", day)
    md = to_md("Burn", lines, "en", day)
    # Markdown: one task per copy, so apps show a box to tick for each.
    assert [line for line in md.splitlines() if line.startswith("- ")] == [
        "- [x] Shock · M21 159 (1/3)",
        "- [ ] Shock · M21 159 (2/3)",
        "- [ ] Shock · M21 159 (3/3)",
    ]
    single = [ShoppingLine(1, 2, "Shock", None, "M21", "159", 1)]
    assert "- [ ] Shock · M21 159\n" in to_md("Burn", single, "en", day)
    # More copies than a row holds still make a PDF.
    many = [ShoppingLine(1, 2, "Relentless Rats", None, "M11", "106", 24)]
    assert to_pdf("Rats", many, "en", day).startswith(b"%PDF")


async def test_nothing_to_buy(client, session, alice, catalog):
    bolt, bolt_printing = catalog["Lightning Bolt"]
    deck = await new_deck(client, alice)
    await put_card(client, alice, deck["id"], bolt, 2)
    await own(client, alice, bolt_printing, 2)
    assert (await client.get(f"/api/decks/{deck['id']}/shopping", headers=alice)).json() == {
        "lines": []
    }
    sent = await client.post(f"/api/decks/{deck['id']}/shopping-list", headers=alice)
    assert sent.status_code == 409
