"""Decks module: decklists, format rules, text import, copies allocated to decks."""

import asyncio

import pytest
from sqlalchemy import func, select

from app.models import Card, CardName, CardSet, CollectionItem, DeckAllocation, Printing
from app.services import deck_import, deck_rules
from app.services.deck_rules import Entry, RuleCard
from tests.conftest import bearer, make_user

LEGAL = {"standard": "legal", "commander": "legal"}
COMMANDER_ONLY = {"commander": "legal"}

# name: (types, subtypes, color identity, legalities, rules text)
CARDS = {
    "Lightning Bolt": (["Instant"], [], ["R"], LEGAL, "Lightning Bolt deals 3 damage."),
    "Mountain": (["Basic", "Land"], ["Mountain"], [], LEGAL, ""),
    "Llanowar Elves": (["Creature"], ["Elf", "Druid"], ["G"], LEGAL, "{T}: Add {G}."),
    "Sol Ring": (["Artifact"], [], [], COMMANDER_ONLY, "{T}: Add {C}{C}."),
    "Black Lotus": (["Artifact"], [], [], {"commander": "banned"}, ""),
    "Relentless Rats": (
        ["Creature"],
        ["Rat"],
        ["B"],
        LEGAL,
        "A deck can have any number of cards named Relentless Rats.",
    ),
    "Krenko, Mob Boss": (
        ["Legendary", "Creature"],
        ["Goblin", "Warrior"],
        ["R"],
        COMMANDER_ONLY,
        "{T}: Create X 1/1 red Goblin creature tokens.",
    ),
    "Thrasios, Triton Hero": (
        ["Legendary", "Creature"],
        ["Merfolk", "Wizard"],
        ["G", "U"],
        COMMANDER_ONLY,
        "{4}: Scry 1, then reveal the top card of your library.\nPartner",
    ),
    "Tymna the Weaver": (
        ["Legendary", "Creature"],
        ["Human", "Cleric"],
        ["W", "B"],
        COMMANDER_ONLY,
        "Lifelink\nPartner (You can have two commanders if both have partner.)",
    ),
    "Delver of Secrets // Insectile Aberration": (
        ["Creature"],
        ["Human", "Wizard", "Insect"],
        ["U"],
        None,
        "",
    ),
    "Shock": (["Instant"], [], ["R"], LEGAL, "Shock deals 2 damage."),
    "Jolt": (["Instant"], [], ["U"], LEGAL, "Untap target artifact."),
}
# Localized names ("Choc" is given to two cards: ambiguous).
NAMES = {"Llanowar Elves": "Elfes de Llanowar", "Shock": "Choc", "Jolt": "Choc"}


@pytest.fixture
async def catalog(session):
    from app.main import register_games

    await register_games()
    card_set = CardSet(game_id="mtg", external_id="tst", code="TST", name="Test Set", lang="en")
    session.add(card_set)
    await session.flush()
    ids = {}
    for number, (name, (types, subtypes, identity, legal, text)) in enumerate(CARDS.items()):
        attributes = {
            "types": types,
            "subtypes": subtypes,
            "color_identity": identity,
            "oracle_text": text,
            "type_line": " ".join(types) + (" — " + " ".join(subtypes) if subtypes else ""),
        }
        if legal is not None:
            attributes["legalities"] = legal
        card = Card(
            game_id="mtg", external_id=name, name=name, colors=identity, attributes=attributes
        )
        session.add(card)
        await session.flush()
        printing = Printing(
            card_id=card.id,
            set_id=card_set.id,
            external_id=str(number),
            collector_number=str(number),
            finishes=["nonfoil", "foil"],
            languages=["en"],
        )
        session.add(printing)
        session.add(CardName(card_id=card.id, lang="en", name=name))
        if name in NAMES:
            session.add(CardName(card_id=card.id, lang="fr", name=NAMES[name]))
        await session.flush()
        ids[name] = (card.id, printing.id)
    await session.commit()
    return ids


async def enable(client, username: str) -> dict:
    headers = await bearer(client, username)
    response = await client.patch("/api/auth/me", json={"modules": ["decks"]}, headers=headers)
    assert response.status_code == 200, response.text
    return headers


@pytest.fixture
async def alice(client, session, catalog):
    await make_user(session)
    return await enable(client, "alice")


async def new_deck(client, headers, name="Burn", fmt="standard") -> dict:
    response = await client.post("/api/decks", json={"name": name, "format": fmt}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def put_card(client, headers, deck_id, card_id, quantity, section="main") -> dict:
    response = await client.put(
        f"/api/decks/{deck_id}/cards",
        json={"card_id": card_id, "quantity": quantity, "section": section},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def own(client, headers, printing_id, delta, condition="NM", finish="nonfoil") -> dict:
    response = await client.post(
        "/api/collection/adjust",
        json={
            "printing_id": printing_id,
            "finish": finish,
            "condition": condition,
            "language": "en",
            "delta": delta,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def entry(detail: dict, card_id: int) -> dict:
    return next(e for e in detail["entries"] if e["card_id"] == card_id)


async def test_module_and_deck_editing(client, session, catalog):
    await make_user(session)
    await make_user(session, "bob")
    plain = await bearer(client, "alice")
    assert (await client.get("/api/decks", headers=plain)).status_code == 403
    alice = await enable(client, "alice")
    bob = await enable(client, "bob")

    formats = (await client.get("/api/decks/formats", headers=alice)).json()
    assert [(g["game_id"], [f["id"] for f in g["formats"]]) for g in formats] == [
        ("mtg", ["standard", "commander"])
    ]
    bad = await client.post("/api/decks", json={"name": "X", "format": "modern"}, headers=alice)
    assert bad.status_code == 422
    other_game = await client.post(
        "/api/decks", json={"name": "X", "format": "standard", "game_id": "pokemon"}, headers=alice
    )
    assert other_game.status_code == 422

    deck = (await new_deck(client, alice))["deck"]
    bolt, _ = catalog["Lightning Bolt"]
    mountain, _ = catalog["Mountain"]
    detail = await put_card(client, alice, deck["id"], bolt, 4)
    detail = await put_card(client, alice, deck["id"], mountain, 20)
    detail = await put_card(client, alice, deck["id"], bolt, 2, "sideboard")
    assert (detail["deck"]["card_count"], detail["deck"]["sideboard_count"]) == (24, 2)
    assert entry(detail, bolt)["quantities"] == {"main": 4, "sideboard": 2}
    assert [e["group"] for e in detail["entries"]] == ["Instant", "Land"]
    codes = {i["code"] for i in detail["validation"]["issues"]}
    assert codes == {"deck_size_min", "copy_limit"}
    detail = await put_card(client, alice, deck["id"], bolt, 0, "sideboard")
    assert entry(detail, bolt)["quantities"] == {"main": 4}

    renamed = await client.patch(
        f"/api/decks/{deck['id']}", json={"name": "Red", "format": "commander"}, headers=alice
    )
    assert (renamed.json()["deck"]["name"], renamed.json()["deck"]["format"]) == (
        "Red",
        "commander",
    )
    assert [d["name"] for d in (await client.get("/api/decks", headers=alice)).json()] == ["Red"]
    # Other users' decks do not exist for them.
    assert (await client.get(f"/api/decks/{deck['id']}", headers=bob)).status_code == 404
    assert (await client.get("/api/decks", headers=bob)).json() == []
    assert (await client.delete(f"/api/decks/{deck['id']}", headers=alice)).status_code == 204
    assert (await client.get("/api/decks", headers=alice)).json() == []


def rule_card(name: str, card_id: int = 0) -> RuleCard:
    types, subtypes, identity, legal, text = CARDS[name]
    attributes = {"types": types, "subtypes": subtypes, "color_identity": identity}
    attributes["oracle_text"] = text
    if legal is not None:
        attributes["legalities"] = legal
    return RuleCard(card_id or hash(name) % 10_000, name, attributes)


def codes(report: deck_rules.Report) -> set[str]:
    return {i.code for i in report.issues}


def test_standard_rules():
    bolt, mountain = rule_card("Lightning Bolt"), rule_card("Mountain")
    rats, ring = rule_card("Relentless Rats"), rule_card("Sol Ring")
    ok = [Entry(bolt, "main", 4), Entry(mountain, "main", 36), Entry(rats, "main", 20)]
    report = deck_rules.check("standard", ok)
    assert report.valid and codes(report) == set()

    report = deck_rules.check(
        "standard",
        [
            Entry(bolt, "main", 4),
            Entry(bolt, "sideboard", 1),
            Entry(mountain, "main", 30),
            Entry(ring, "main", 1),
            Entry(mountain, "sideboard", 15),
            Entry(rule_card("Delver of Secrets // Insectile Aberration"), "main", 4),
        ],
    )
    assert not report.valid
    assert codes(report) == {"deck_size_min", "copy_limit", "sideboard_max", "not_legal"}
    copy = next(i for i in report.issues if i.code == "copy_limit")
    assert (copy.params["name"], copy.params["count"], copy.params["limit"]) == (
        "Lightning Bolt",
        5,
        4,
    )
    unverified = {i.code: i for i in report.unverified}
    assert unverified["legality_unknown"].params["names"] == [
        "Delver of Secrets // Insectile Aberration"
    ]


def test_commander_rules():
    krenko, bolt = rule_card("Krenko, Mob Boss"), rule_card("Lightning Bolt")
    mountain, elves = rule_card("Mountain"), rule_card("Llanowar Elves")
    deck = [Entry(krenko, "commander", 1), Entry(bolt, "main", 1), Entry(mountain, "main", 98)]
    report = deck_rules.check("commander", deck)
    # Lightning Bolt and Mountain are legal, Krenko leads red.
    assert report.valid, report.issues

    report = deck_rules.check(
        "commander",
        [
            Entry(krenko, "commander", 1),
            Entry(bolt, "main", 2),
            Entry(elves, "main", 1),
            Entry(rule_card("Black Lotus"), "main", 1),
            Entry(mountain, "main", 90),
            Entry(bolt, "sideboard", 3),
        ],
    )
    assert codes(report) == {
        "deck_size_exact",
        "copy_limit",
        "color_identity",
        "banned",
        "sideboard_ignored",
    }
    identity = next(i for i in report.issues if i.code == "color_identity")
    assert (identity.params["name"], identity.params["colors"]) == ("Llanowar Elves", "G")

    assert "no_commander" in codes(deck_rules.check("commander", deck[1:]))
    not_legendary = deck_rules.check("commander", [Entry(elves, "commander", 1), *deck[1:]])
    assert "invalid_commander" in codes(not_legendary)
    partners = [
        Entry(rule_card("Thrasios, Triton Hero"), "commander", 1),
        Entry(rule_card("Tymna the Weaver"), "commander", 1),
        Entry(mountain, "main", 98),
    ]
    assert "commander_pair" not in codes(deck_rules.check("commander", partners))
    no_pair = [Entry(krenko, "commander", 1), *partners[1:]]
    assert "commander_pair" in codes(deck_rules.check("commander", no_pair))


def test_parse_decklist():
    parsed = deck_import.parse(
        """// Burn
Commander
1 Krenko, Mob Boss *CMDR*

Deck
4 Lightning Bolt (M10) 146
4x Shock [M19]
Delver of Secrets / Insectile Aberration
20 Mountain #Land

Sideboard (2)
2 Shock
SB: 1 Sol Ring
Maybeboard
1 Black Lotus
banana
"""
    )
    assert [(line.quantity, line.name, line.section) for line in parsed.lines] == [
        (1, "Krenko, Mob Boss", "commander"),
        (4, "Lightning Bolt", "main"),
        (4, "Shock", "main"),
        (1, "Delver of Secrets // Insectile Aberration", "main"),
        (20, "Mountain", "main"),
        (2, "Shock", "sideboard"),
        (1, "Sol Ring", "sideboard"),
    ]
    assert parsed.lines[0].number == 3


async def test_import_preview_and_import(client, session, alice):
    text = """Commander
1 Krenko, Mob Boss
Deck
4 lightning bolt
1 Delver of Secrets
2 Elfes de Llanowar
1 Choc
1 Lightnig Bolt
"""
    preview = await client.post("/api/decks/import/preview", json={"text": text}, headers=alice)
    assert preview.status_code == 200, preview.text
    lines = {line["text"]: line for line in preview.json()["lines"]}
    assert lines["1 Krenko, Mob Boss"]["section"] == "commander"
    assert lines["4 lightning bolt"]["card"]["name"] == "Lightning Bolt"
    assert lines["1 Delver of Secrets"]["card"]["name"].startswith("Delver of Secrets //")
    assert lines["2 Elfes de Llanowar"]["card"]["name"] == "Llanowar Elves"
    assert lines["1 Choc"]["status"] == "ambiguous"
    assert {c["name"] for c in lines["1 Choc"]["candidates"]} == {"Shock", "Jolt"}
    unknown = lines["1 Lightnig Bolt"]
    assert unknown["status"] == "unknown"
    assert unknown["candidates"][0]["name"] == "Lightning Bolt"

    deck = (await new_deck(client, alice, "Goblins", "commander"))["deck"]
    owned = await own(client, alice, await _printing(session, "Lightning Bolt"), 3)
    entries = [
        {
            "card_id": line["card"]["card_id"],
            "section": line["section"],
            "quantity": line["quantity"],
        }
        for line in preview.json()["lines"]
        if line["status"] == "resolved"
    ]
    # The user picks Shock for the ambiguous line, the suggestion for the unknown one.
    entries.append({"card_id": lines["1 Choc"]["candidates"][0]["card_id"], "quantity": 1})
    entries.append({"card_id": unknown["candidates"][0]["card_id"], "quantity": 1})
    imported = await client.post(
        f"/api/decks/{deck['id']}/import", json={"entries": entries}, headers=alice
    )
    assert imported.status_code == 200, imported.text
    detail = imported.json()
    bolt = next(e for e in detail["entries"] if e["name"] == "Lightning Bolt")
    assert bolt["requested"] == 5
    # Importing does not touch the collection nor allocate anything.
    assert (bolt["owned"], bolt["allocated"], bolt["available"], bolt["status"]) == (
        3,
        0,
        3,
        "missing",
    )
    assert owned["item"]["quantity"] == 3
    assert await session.scalar(select(func.count()).select_from(DeckAllocation)) == 0
    assert detail["deck"]["card_count"] == 10

    # Replacing the list releases allocations of the cards that leave it.
    await client.post(
        f"/api/decks/{deck['id']}/allocate",
        json={"card_id": bolt["card_id"], "quantity": 2},
        headers=alice,
    )
    replaced = await client.post(
        f"/api/decks/{deck['id']}/import",
        json={"entries": entries[:1], "replace": True},
        headers=alice,
    )
    assert [e["name"] for e in replaced.json()["entries"]] == ["Krenko, Mob Boss"]
    assert await session.scalar(select(func.count()).select_from(DeckAllocation)) == 0


async def _printing(session, name: str) -> int:
    return await session.scalar(select(Printing.id).join(Card).where(Card.name == name))


async def quantity(session, item_id: int) -> int:
    return await session.scalar(
        select(CollectionItem.quantity)
        .where(CollectionItem.id == item_id)
        .execution_options(populate_existing=True)
    )


async def test_allocation_across_two_decks(client, session, alice, catalog):
    bolt, printing = catalog["Lightning Bolt"]
    burn = (await new_deck(client, alice, "Burn"))["deck"]["id"]
    izzet = (await new_deck(client, alice, "Izzet"))["deck"]["id"]
    nm = (await own(client, alice, printing, 2))["item"]["id"]
    lp = (await own(client, alice, printing, 1, condition="LP"))["item"]["id"]
    await put_card(client, alice, burn, bolt, 4)
    detail = await put_card(client, alice, izzet, bolt, 2)
    # In the list, nothing allocated yet: all 3 owned copies available.
    assert {
        k: entry(detail, bolt)[k] for k in ("requested", "owned", "allocated", "available")
    } == {
        "requested": 2,
        "owned": 3,
        "allocated": 0,
        "available": 3,
    }
    assert entry(detail, bolt)["status"] == "owned"

    async def allocate(deck_id, count, item_id=None, path="allocate"):
        return await client.post(
            f"/api/decks/{deck_id}/{path}",
            json={"card_id": bolt, "quantity": count, "item_id": item_id},
            headers=alice,
        )

    detail = (await allocate(burn, 2)).json()
    assert (entry(detail, bolt)["allocated"], entry(detail, bolt)["available"]) == (2, 1)
    assert entry(detail, bolt)["status"] == "missing"  # 4 asked, 2 here, 1 free
    other = (await client.get(f"/api/decks/{izzet}", headers=alice)).json()
    assert {k: entry(other, bolt)[k] for k in ("available", "allocated_elsewhere", "status")} == {
        "available": 1,
        "allocated_elsewhere": 2,
        "status": "missing",
    }
    refused = await allocate(izzet, 2)
    assert refused.status_code == 409
    assert "Only 1 owned copies are available" in refused.json()["detail"]
    detail = (await allocate(izzet, 1, item_id=lp)).json()
    assert (entry(detail, bolt)["allocated"], entry(detail, bolt)["available"]) == (1, 0)
    assert (await allocate(burn, 1)).status_code == 409  # none left
    # Owned quantities never change.
    assert (await quantity(session, nm), await quantity(session, lp)) == (2, 1)
    items = (await client.get(f"/api/decks/{izzet}/cards/{bolt}/items", headers=alice)).json()
    assert [
        (i["condition"], i["allocated"], i["allocated_elsewhere"], i["free"]) for i in items
    ] == [
        ("NM", 0, 2, 0),
        ("LP", 1, 0, 0),
    ]

    # Not more than the deck asks for.
    await allocate(izzet, 1, path="release")
    await put_card(client, alice, burn, bolt, 2)  # 2 allocated, 2 asked: nothing released
    assert (await allocate(burn, 1)).status_code == 409
    assert "asks for 2" in (await allocate(burn, 1)).json()["detail"]
    detail = await put_card(client, alice, burn, bolt, 1)
    assert entry(detail, bolt)["allocated"] == 1  # lowered: excess released
    assert (await allocate(burn, 5, path="release")).status_code == 409

    # Removing the card or the deck releases its copies.
    detail = await put_card(client, alice, burn, bolt, 0)
    assert detail["entries"] == []
    detail = (await allocate(izzet, 2)).json()
    assert entry(detail, bolt)["allocated"] == 2
    await client.delete(f"/api/decks/{izzet}", headers=alice)
    assert await session.scalar(select(func.count()).select_from(DeckAllocation)) == 0
    assert (await quantity(session, nm), await quantity(session, lp)) == (2, 1)


async def test_collection_reductions_trim_allocations(client, session, alice, catalog):
    bolt, printing = catalog["Lightning Bolt"]
    first = (await new_deck(client, alice, "One"))["deck"]["id"]
    second = (await new_deck(client, alice, "Two"))["deck"]["id"]
    item = (await own(client, alice, printing, 3))["item"]["id"]
    for deck_id in (first, second):
        await put_card(client, alice, deck_id, bolt, 4)
    await client.post(
        f"/api/decks/{first}/allocate", json={"card_id": bolt, "quantity": 2}, headers=alice
    )
    await client.post(
        f"/api/decks/{second}/allocate", json={"card_id": bolt, "quantity": 1}, headers=alice
    )

    async def allocated(deck_id):
        detail = (await client.get(f"/api/decks/{deck_id}", headers=alice)).json()
        return entry(detail, bolt)["allocated"], entry(detail, bolt)["available"]

    # Selling one copy: the latest allocation gives it back.
    removed = await own(client, alice, printing, -1)
    assert removed["item"]["quantity"] == 2
    assert (await allocated(first), await allocated(second)) == ((2, 0), (0, 0))
    # Undoing an addition, setting the quantity, deleting the item.
    added = await own(client, alice, printing, 1)
    await client.post(
        f"/api/decks/{second}/allocate", json={"card_id": bolt, "quantity": 1}, headers=alice
    )
    undo = await client.post(
        f"/api/collection/transactions/{added['transaction_id']}/undo", headers=alice
    )
    assert undo.status_code == 200, undo.text
    assert (await allocated(first), await allocated(second)) == ((2, 0), (0, 0))
    patched = await client.patch(
        f"/api/collection/items/{item}", json={"quantity": 1}, headers=alice
    )
    assert patched.status_code == 200, patched.text
    assert await allocated(first) == (1, 0)
    await client.delete(f"/api/collection/items/{item}", headers=alice)
    assert await allocated(first) == (0, 0)


async def test_concurrent_allocations_never_exceed_owned(client, session, alice, catalog):
    bolt, printing = catalog["Lightning Bolt"]
    await own(client, alice, printing, 3)
    decks = [(await new_deck(client, alice, f"Deck {n}"))["deck"]["id"] for n in range(4)]
    for deck_id in decks:
        await put_card(client, alice, deck_id, bolt, 4)
    responses = await asyncio.gather(
        *(
            client.post(
                f"/api/decks/{deck_id}/allocate",
                json={"card_id": bolt, "quantity": 2},
                headers=alice,
            )
            for deck_id in decks
        )
    )
    assert sorted(r.status_code for r in responses) == [200, 409, 409, 409]
    total = await session.scalar(select(func.sum(DeckAllocation.quantity)))
    assert total == 2


async def test_deck_cards_survive_catalog_pruning(session, alice, client, catalog):
    from app.services.catalog import reset_catalog

    bolt, _ = catalog["Lightning Bolt"]
    deck = (await new_deck(client, alice))["deck"]["id"]
    await put_card(client, alice, deck, bolt, 4)
    await reset_catalog(session, "mtg")
    assert await session.get(Card, bolt) is not None
    assert await session.scalar(select(func.count()).select_from(Card)) == 1
