# ruff: noqa: F811 (fixtures imported from test_decks)
"""Shopping lists: standalone lists for every user, lists linked to a deck (Decks module)
or a followed set (Binder module) rebuilt on request with their ticks kept, and the
files (.txt, .md, .pdf)."""

import asyncio
from datetime import date

from sqlalchemy import select, update

from app.models import BinderSet, CardSet, Printing
from app.services.decks import line_missing
from app.services.shopping import Edition, ShoppingLine, to_md, to_pdf, to_txt
from tests.conftest import bearer, make_user
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


async def sync(client, headers, deck_id) -> dict:
    response = await client.post(f"/api/decks/{deck_id}/shopping-list", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def tick(client, headers, found, item, count) -> dict:
    response = await client.patch(
        f"/api/shopping-lists/{found['id']}/items/{item['id']}",
        json={"bought_count": count},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def boxes(found: dict) -> list[tuple[str, int, int]]:
    return [(i["name"], i["quantity"], i["bought_count"]) for i in found["items"]]


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
    assert detail["shopping_list_id"] is None

    made = await sync(client, alice, burn["id"])
    assert made["status"] == "created"
    assert boxes(made["list"]) == [("Lightning Bolt", 3, 0)]
    detail = (await client.get(f"/api/decks/{burn['id']}", headers=alice)).json()
    assert detail["shopping_list_id"] == made["list"]["id"]


async def test_standalone_list_without_modules(client, session, catalog):
    """Acceptance 1: no module, a standalone list of two copies, one ticked; adding the
    card to the collection leaves the ticks alone."""
    bolt, bolt_printing = catalog["Lightning Bolt"]
    await make_user(session, "carol")
    carol = await bearer(client, "carol")
    assert (await client.get("/api/auth/me", headers=carol)).json()["modules"] == []
    # Decks stay closed, lists are open.
    assert (await client.get("/api/decks", headers=carol)).status_code == 403
    assert (await client.get("/api/shopping-lists", headers=carol)).json() == []

    made = await client.post(
        "/api/shopping-lists", json={"name": "Wishlist", "game_id": "mtg"}, headers=carol
    )
    assert made.status_code == 201, made.text
    found = made.json()
    assert (found["name"], found["source"], found["items"]) == ("Wishlist", None, [])
    assert (
        await client.post(
            "/api/shopping-lists", json={"name": "X", "game_id": "nope"}, headers=carol
        )
    ).status_code == 422

    added = await client.post(
        f"/api/shopping-lists/{found['id']}/items",
        json={"card_id": bolt, "quantity": 2, "printing_ids": [bolt_printing]},
        headers=carol,
    )
    assert added.status_code == 201, added.text
    item = added.json()["items"][0]
    assert (item["quantity"], item["manual"], item["set_code"]) == (2, True, "TST")
    assert [e["printing_id"] for e in item["editions"]] == [bolt_printing]
    # Another card's printing is refused.
    other = catalog["Mountain"][1]
    assert (
        await client.post(
            f"/api/shopping-lists/{found['id']}/items",
            json={"card_id": bolt, "printing_ids": [other]},
            headers=carol,
        )
    ).status_code == 422

    ticked = await tick(client, carol, found, item, 1)
    assert (ticked["copies"], ticked["bought"]) == (2, 1)
    await own(client, carol, bolt_printing, 2)
    again = (await client.get(f"/api/shopping-lists/{found['id']}", headers=carol)).json()
    assert (again["copies"], again["bought"]) == (2, 1)

    url = f"/api/shopping-lists/{found['id']}/download"
    assert "[x][ ] 2 Lightning Bolt · TST 0" in (await client.get(url, headers=carol)).text
    md = (await client.get(url, params={"format": "md"}, headers=carol)).text
    assert "- [x] Lightning Bolt · TST 0 (1/2)" in md
    assert "- [ ] Lightning Bolt · TST 0 (2/2)" in md
    pdf = await client.get(url, params={"format": "pdf"}, headers=carol)
    assert pdf.content.startswith(b"%PDF")

    # Rename, any edition, more copies, remove.
    renamed = await client.patch(
        f"/api/shopping-lists/{found['id']}", json={"name": "Wants"}, headers=carol
    )
    assert renamed.json()["name"] == "Wants"
    item_url = f"/api/shopping-lists/{found['id']}/items/{item['id']}"
    changed = await client.patch(item_url, json={"printing_ids": [], "quantity": 3}, headers=carol)
    assert changed.status_code == 200, changed.text
    out = changed.json()["items"][0]
    assert (out["editions"], out["printing_id"], out["quantity"], out["bought_count"]) == (
        [],
        None,
        3,
        1,
    )
    # Fewer copies than ticked: the ticks follow.
    assert (await client.patch(item_url, json={"quantity": 1}, headers=carol)).json()["items"][0][
        "bought_count"
    ] == 1
    gone = await client.delete(item_url, headers=carol)
    assert gone.json()["items"] == []


async def test_deck_list_refresh(client, session, alice, catalog):
    """Acceptance 2 and 3: ticks survive refreshes, a bought copy reaching the collection
    removes a ticked copy, a complete deck loses its list."""
    bolt, bolt_printing = catalog["Lightning Bolt"]
    shock, _ = catalog["Shock"]
    deck = await new_deck(client, alice)
    await put_card(client, alice, deck["id"], bolt, 2)

    made = await sync(client, alice, deck["id"])
    assert made["status"] == "created"
    found = made["list"]
    assert (found["source"], found["deck_id"], found["name"]) == ("deck", deck["id"], "Burn")
    assert boxes(found) == [("Lightning Bolt", 2, 0)]
    await tick(client, alice, found, found["items"][0], 1)

    for _ in range(2):
        refreshed = await sync(client, alice, deck["id"])
        assert refreshed["status"] == "updated"
        assert refreshed["list"]["id"] == found["id"]
        assert boxes(refreshed["list"]) == [("Lightning Bolt", 2, 1)]

    # The bought copy reaches the collection: one copy left, not ticked.
    await own(client, alice, bolt_printing, 1)
    refreshed = await sync(client, alice, deck["id"])
    assert boxes(refreshed["list"]) == [("Lightning Bolt", 1, 0)]
    md = await client.get(
        f"/api/shopping-lists/{found['id']}/download", params={"format": "md"}, headers=alice
    )
    assert "- [ ] Lightning Bolt\n" in md.text

    # More copies wanted: new copies come unticked, ticked ones stay.
    await tick(client, alice, refreshed["list"], refreshed["list"]["items"][0], 1)
    await put_card(client, alice, deck["id"], bolt, 4)
    refreshed = await sync(client, alice, deck["id"])
    assert boxes(refreshed["list"]) == [("Lightning Bolt", 3, 1)]

    # A card added by hand goes at the next refresh; a list of its own stays.
    await client.post(
        f"/api/shopping-lists/{found['id']}/items", json={"card_id": shock}, headers=alice
    )
    own_list = await client.post(
        "/api/shopping-lists", json={"name": "Mine", "game_id": "mtg"}, headers=alice
    )
    refreshed = await sync(client, alice, deck["id"])
    assert boxes(refreshed["list"]) == [("Lightning Bolt", 3, 1)]

    # Complete: the list is deleted, the button makes one again.
    await client.post(
        f"/api/shopping-lists/{found['id']}/items", json={"card_id": shock}, headers=alice
    )
    await own(client, alice, bolt_printing, 3)
    done = await sync(client, alice, deck["id"])
    assert (done["status"], done["list"]) == ("deleted", None)
    assert (
        await client.get(f"/api/shopping-lists/{found['id']}", headers=alice)
    ).status_code == 404
    lists = (await client.get("/api/shopping-lists", headers=alice)).json()
    assert [x["id"] for x in lists] == [own_list.json()["id"]]
    assert (await sync(client, alice, deck["id"]))["status"] == "nothing"
    detail = (await client.get(f"/api/decks/{deck['id']}", headers=alice)).json()
    assert detail["shopping_list_id"] is None


async def test_deck_list_owner_and_source(client, session, alice, catalog):
    bolt, _ = catalog["Lightning Bolt"]
    deck = await new_deck(client, alice)
    await put_card(client, alice, deck["id"], bolt, 4)

    # Two requests together still make one list.
    first, second = await asyncio.gather(
        client.post(f"/api/decks/{deck['id']}/shopping-list", headers=alice),
        client.post(f"/api/decks/{deck['id']}/shopping-list", headers=alice),
    )
    assert {first.status_code, second.status_code} == {200}
    assert sorted([first.json()["status"], second.json()["status"]]) == ["created", "updated"]
    lists = (await client.get("/api/shopping-lists", headers=alice)).json()
    assert len(lists) == 1
    found = lists[0]
    item = (await client.get(f"/api/shopping-lists/{found['id']}", headers=alice)).json()["items"][
        0
    ]

    # Another user sees nothing and cannot change, export or delete it.
    await make_user(session, "bob")
    bob = await enable(client, "bob")
    assert (await client.get("/api/shopping-lists", headers=bob)).json() == []
    base = f"/api/shopping-lists/{found['id']}"
    for method, url, body in (
        ("GET", base, None),
        ("GET", f"{base}/download", None),
        ("PATCH", base, {"name": "x"}),
        ("POST", f"{base}/items", {"card_id": bolt}),
        ("PATCH", f"{base}/items/{item['id']}", {"bought": True}),
        ("DELETE", f"{base}/items/{item['id']}", None),
        ("DELETE", base, None),
    ):
        response = await client.request(method, url, json=body, headers=bob)
        assert response.status_code == 404, (method, url)
    assert (
        await client.post(f"/api/decks/{deck['id']}/shopping-list", headers=bob)
    ).status_code == 404

    # The list stays, standalone, when the deck goes.
    assert (await client.delete(f"/api/decks/{deck['id']}", headers=alice)).status_code == 204
    lists = (await client.get("/api/shopping-lists", headers=alice)).json()
    assert [(x["id"], x["source"], x["deck_id"], x["copies"]) for x in lists] == [
        (found["id"], None, None, 4)
    ]

    # Without the Decks module the deck's button is closed, the list stays open.
    await client.patch("/api/auth/me", json={"modules": []}, headers=alice)
    assert (await client.get(base, headers=alice)).status_code == 200
    assert (await client.post("/api/decks/1/shopping-list", headers=alice)).status_code == 403
    assert (await client.post("/api/binder/1/shopping-list", headers=alice)).status_code == 403


async def test_followed_set_list(client, session, alice, catalog):
    """Acceptance 3: a set followed in French foil keeps a card until a French foil copy
    of that printing is owned."""
    await client.patch("/api/auth/me", json={"modules": ["decks", "binder"]}, headers=alice)
    bolt_printing = catalog["Lightning Bolt"][1]
    await session.execute(update(Printing).values(languages=["en", "fr"]))
    card_set = await session.scalar(select(CardSet.id).where(CardSet.code == "TST"))
    me = (await client.get("/api/auth/me", headers=alice)).json()
    binder = BinderSet(user_id=me["id"], set_id=card_set, language="fr", finish="foil")
    session.add(binder)
    await session.commit()
    total = len(catalog)

    made = (await client.post(f"/api/binder/{binder.id}/shopping-list", headers=alice)).json()
    assert made["status"] == "created"
    found = made["list"]
    assert (found["source"], found["binder_id"], found["name"]) == ("binder", binder.id, "Test Set")
    assert found["copies"] == total
    bolt_item = next(i for i in found["items"] if i["name"] == "Lightning Bolt")
    assert (bolt_item["language"], bolt_item["finish"], bolt_item["quantity"]) == ("fr", "foil", 1)
    assert [e["printing_id"] for e in bolt_item["editions"]] == [bolt_printing]
    await tick(client, alice, found, bolt_item, 1)
    detail = (await client.get(f"/api/binder/{binder.id}", headers=alice)).json()
    assert detail["shopping_list_id"] == found["id"]

    async def adjust(language, finish):
        response = await client.post(
            "/api/collection/adjust",
            json={
                "printing_id": bolt_printing,
                "finish": finish,
                "condition": "NM",
                "language": language,
                "delta": 1,
            },
            headers=alice,
        )
        assert response.status_code == 200, response.text

    def bolt(found):
        return [i for i in found["items"] if i["name"] == "Lightning Bolt"]

    url = f"/api/binder/{binder.id}/shopping-list"
    for language, finish in (("en", "foil"), ("fr", "nonfoil")):
        await adjust(language, finish)
        kept = (await client.post(url, headers=alice)).json()["list"]
        assert [(i["quantity"], i["bought_count"]) for i in bolt(kept)] == [(1, 1)]
    await adjust("fr", "foil")
    kept = (await client.post(url, headers=alice)).json()["list"]
    assert bolt(kept) == []
    assert kept["copies"] == total - 1
    txt = (await client.get(f"/api/shopping-lists/{found['id']}/download", headers=alice)).text
    assert "FR foil" in txt

    # Unfollowed: the list stays as a standalone list.
    assert (await client.delete(f"/api/binder/{binder.id}", headers=alice)).status_code == 204
    lists = (await client.get("/api/shopping-lists", headers=alice)).json()
    assert [(x["id"], x["source"]) for x in lists] == [(found["id"], None)]


def test_copy_boxes():
    edition = [Edition(2, "M21", "159")]
    lines = [ShoppingLine(1, "Shock", None, 3, edition, bought=1)]
    day = date(2026, 11, 22)
    assert "[x][ ][ ] 3 Shock · M21 159" in to_txt("Burn", lines, "en", day)
    md = to_md("Burn", lines, "en", day)
    # Markdown: one task per copy, so apps show a box to tick for each.
    assert [line for line in md.splitlines() if line.startswith("- ")] == [
        "- [x] Shock · M21 159 (1/3)",
        "- [ ] Shock · M21 159 (2/3)",
        "- [ ] Shock · M21 159 (3/3)",
    ]
    single = [ShoppingLine(1, "Shock", None, 1, edition)]
    assert "- [ ] Shock · M21 159\n" in to_md("Burn", single, "en", day)
    # Several editions, language and finish.
    either = [
        ShoppingLine(
            1,
            "Lightning Bolt",
            "Foudre",
            2,
            [Edition(3, "M10", "146"), Edition(4, "2X2", "117")],
            language="fr",
            finish="foil",
        )
    ]
    assert "[ ][ ] 2 Lightning Bolt (Foudre) · M10 146 / 2X2 117 · FR foil" in to_txt(
        "Burn", either, "en", day
    )
    # More copies than a row holds still make a PDF.
    many = [ShoppingLine(1, "Relentless Rats", None, 24, [Edition(2, "M11", "106")])]
    assert to_pdf("Rats", many, "en", day).startswith(b"%PDF")


async def test_shopping_files_in_language(client, session, alice, catalog):
    elves, elves_printing = catalog["Llanowar Elves"]
    deck = await new_deck(client, alice, "Elves/Bolt")
    await put_line(client, alice, deck["id"], elves, 4, elves_printing)
    await client.patch("/api/auth/me", json={"language": "fr"}, headers=alice)
    found = (await sync(client, alice, deck["id"]))["list"]

    url = f"/api/shopping-lists/{found['id']}/download"
    txt = await client.get(url, headers=alice)
    assert txt.headers["content-type"].startswith("text/plain")
    assert 'filename="Elves_Bolt.txt"' in txt.headers["content-disposition"]
    assert "Liste d'achats" in txt.text
    assert "[ ][ ][ ][ ] 4 Llanowar Elves (Elfes de Llanowar) · TST 2" in txt.text
    assert (await client.get(url, params={"format": "doc"}, headers=alice)).status_code == 422
