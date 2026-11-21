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
        (game_id, list(ids)) for game_id, ids in deck_rules.GAMES.items()
    ]
    bad = await client.post("/api/decks", json={"name": "X", "format": "historic"}, headers=alice)
    assert bad.status_code == 422
    other_game = await client.post(
        "/api/decks", json={"name": "X", "format": "standard", "game_id": "pokemon"}, headers=alice
    )
    assert other_game.status_code == 422
    pokemon = await client.post(
        "/api/decks",
        json={"name": "Pika", "format": "pokemon_standard", "game_id": "pokemon"},
        headers=alice,
    )
    assert pokemon.status_code == 201, pokemon.text
    assert pokemon.json()["groups"][0] == "Pokémon"
    to_magic = await client.patch(
        f"/api/decks/{pokemon.json()['deck']['id']}", json={"format": "modern"}, headers=alice
    )
    assert to_magic.status_code == 422
    await client.delete(f"/api/decks/{pokemon.json()['deck']['id']}", headers=alice)

    deck = (await new_deck(client, alice))["deck"]
    bolt, _ = catalog["Lightning Bolt"]
    mountain, _ = catalog["Mountain"]
    detail = await put_card(client, alice, deck["id"], bolt, 4)
    detail = await put_card(client, alice, deck["id"], mountain, 20)
    detail = await put_card(client, alice, deck["id"], bolt, 2, "sideboard")
    assert (detail["deck"]["card_count"], detail["deck"]["counts"]) == (
        24,
        {"main": 24, "sideboard": 2},
    )
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
    # A sound deck has nothing "not verified" either.
    assert report.unverified == []
    # Un-set cards with their own deck: named in a note only when there.
    ride = RuleCard(99, "Bumper Cars", {"types": ["Artifact"], "subtypes": ["Attraction"]})
    note = deck_rules.check("standard", [*ok, Entry(ride, "main", 1)]).unverified
    assert [(i.code, i.params["names"]) for i in note if i.code == "not_modelled"] == [
        ("not_modelled", ["Bumper Cars"])
    ]

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


def card(card_id: int, name: str, types: list[str], identity: list[str], legal: dict, text=""):
    attributes = {"types": types, "subtypes": [], "color_identity": identity}
    attributes |= {"oracle_text": text, "legalities": legal}
    return RuleCard(card_id, name, attributes)


def test_other_formats():
    # Every format is a Scryfall legality key; no Arena-only format.
    assert {"modern", "vintage", "paupercommander", "oathbreaker"} <= set(deck_rules.FORMATS)
    assert not {"historic", "alchemy", "brawl", "gladiator"} & set(deck_rules.FORMATS)

    swamps = card(1, "Swamp", ["Basic", "Land"], [], {f: "legal" for f in deck_rules.FORMATS})
    vintage = {"vintage": "restricted", "legacy": "banned"}
    lotus = card(2, "Black Lotus", ["Artifact"], [], vintage)
    report = deck_rules.check("vintage", [Entry(lotus, "main", 2), Entry(swamps, "main", 58)])
    assert codes(report) == {"restricted"}
    assert deck_rules.check("vintage", [Entry(lotus, "main", 1), Entry(swamps, "main", 59)]).valid
    assert "banned" in codes(deck_rules.check("legacy", [Entry(lotus, "main", 1)]))

    # Pauper Commander: any creature leads (an uncommon: not legal in the 99 itself).
    rats = card(3, "Chittering Rats", ["Creature"], ["B"], {})
    pdh = [Entry(rats, "commander", 1), Entry(swamps, "main", 99)]
    report = deck_rules.check("paupercommander", pdh)
    assert report.valid, report.issues
    assert "commander_rarity" in {i.code for i in report.unverified}
    sorin = card(4, "Sorin", ["Legendary", "Planeswalker"], ["B"], {})
    report = deck_rules.check("paupercommander", [Entry(sorin, "commander", 1), *pdh[1:]])
    assert "invalid_commander_creature" in codes(report)

    # Oathbreaker: a planeswalker and its signature spell, 60 cards.
    oath = {"oathbreaker": "legal"}
    liliana = card(5, "Liliana", ["Legendary", "Planeswalker"], ["B"], oath)
    edict = card(6, "Diabolic Edict", ["Instant"], ["B"], oath)
    bolt = card(7, "Lightning Bolt", ["Instant"], ["R"], oath)
    deck = [Entry(liliana, "commander", 1), Entry(edict, "commander", 1), Entry(swamps, "main", 58)]
    report = deck_rules.check("oathbreaker", deck)
    assert report.valid, report.issues
    assert "signature_spells" in codes(deck_rules.check("oathbreaker", deck[::2]))
    off_color = deck_rules.check("oathbreaker", [deck[0], Entry(bolt, "commander", 1), deck[2]])
    assert "color_identity" in codes(off_color)
    assert "no_oathbreaker" in codes(deck_rules.check("oathbreaker", deck[1:]))
    rats_too = deck_rules.check("oathbreaker", [*deck, Entry(rats, "commander", 1)])
    assert "invalid_oathbreaker" in codes(rats_too)


def mtg(
    card_id: int, name: str, type_line: str, cmc: float, cost: str = "", text: str = "", **more
):
    types, _, subtypes = type_line.partition("—")
    attributes = {"types": types.split(), "subtypes": subtypes.split(), "color_identity": []}
    attributes |= {"cmc": cmc, "mana_cost": cost, "oracle_text": text}
    attributes |= {"legalities": {"modern": "legal", "legacy": "legal", "commander": "legal"}}
    return RuleCard(card_id, name, attributes | more)


def companion_check(companion: RuleCard, main: list[Entry], fmt: str = "modern"):
    report = deck_rules.check(fmt, [*main, Entry(companion, "companion", 1)])
    return next((i for i in report.issues if i.code == "companion"), None), report


def test_companions():
    mountain = mtg(1, "Mountain", "Basic Land — Mountain", 0, text="({T}: Add {R}.)")
    bolt = mtg(2, "Lightning Bolt", "Instant", 1, "{R}")
    giant = mtg(3, "Stone Giant", "Creature — Giant", 4, "{2}{R}{R}")
    cat = mtg(4, "Savannah Lions", "Creature — Cat Soldier", 1, "{W}")
    ox = mtg(5, "Ox of Agonas", "Creature — Ox", 2, "{3}{R}{R}", "{1}: Ox gets +1/+0.")
    lurrus = mtg(10, "Lurrus of the Dream-Den", "Legendary Creature — Cat Nightmare", 3)
    yorion = mtg(11, "Yorion, Sky Nomad", "Legendary Creature — Bird Serpent", 5)
    kaheera = mtg(12, "Kaheera, the Orphanguard", "Legendary Creature — Cat Beast", 3)
    jegantha = mtg(13, "Jegantha, the Wellspring", "Legendary Creature — Elemental Elk", 5)
    lutri = mtg(14, "Lutri, the Spellchaser", "Legendary Creature — Elemental Otter", 3)
    umori = mtg(15, "Umori, the Collector", "Legendary Creature — Ooze", 4)
    zirda = mtg(16, "Zirda, the Dawnwaker", "Legendary Creature — Elemental Fox", 3)
    gyruda = mtg(17, "Gyruda, Doom of Depths", "Legendary Creature — Demon Kraken", 6)
    base = [Entry(mountain, "main", 20), Entry(bolt, "main", 4), Entry(cat, "main", 36)]

    # Lurrus: permanents of mana value 2 or less (instants and lands do not matter).
    # (Copy limits are not the point here.)
    assert companion_check(lurrus, base)[0] is None
    issue, report = companion_check(lurrus, [*base[:2], Entry(giant, "main", 36)])
    assert issue.params["rule"] == "lurrus" and issue.params["names"] == ["Stone Giant"]
    assert issue.level == "error" and not report.valid
    # In the main deck or the sideboard it is just a creature: not a companion.
    big = [*base[:2], Entry(giant, "main", 36)]
    for section in ("main", "sideboard"):
        report = deck_rules.check("modern", [*big, Entry(lurrus, section, 1)])
        assert "companion" not in codes(report)
    # The companion is one of the sideboard's 15 cards.
    side = [Entry(mountain, "sideboard", 14)]
    assert "sideboard_max" not in codes(companion_check(lurrus, [*base, *side])[1])
    side = [Entry(mountain, "sideboard", 15)]
    assert "sideboard_max" in codes(companion_check(lurrus, [*base, *side])[1])
    # One companion, and a companion card.
    report = deck_rules.check(
        "modern", [*base, Entry(lurrus, "companion", 1), Entry(kaheera, "companion", 1)]
    )
    assert "companion_count" in codes(report)
    issue = next(i for i in companion_check(cat, base)[1].issues if i.code == "not_companion")
    assert issue.params["name"] == "Savannah Lions"

    # Yorion: 20 cards over the minimum; never in a 100-card singleton format.
    assert companion_check(yorion, base)[0].params == {
        "name": yorion.name,
        "rule": "yorion",
        "names": [],
        "size": 80,
    }
    assert companion_check(yorion, [*base, Entry(cat, "main", 20)])[0] is None

    # Kaheera: creature types; Jegantha: no repeated mana symbol; Lutri: singleton.
    assert companion_check(kaheera, base)[0] is None
    assert companion_check(kaheera, [*base, Entry(giant, "main", 1)])[0].params["names"] == [
        "Stone Giant"
    ]
    assert companion_check(jegantha, [*base, Entry(giant, "main", 1)])[0].params["names"] == [
        "Stone Giant"
    ]
    assert companion_check(jegantha, base)[0] is None
    assert companion_check(lutri, base)[0].params["names"] == ["Lightning Bolt", "Savannah Lions"]
    # Umori: every nonland card shares a type; Gyruda: even mana values.
    assert companion_check(umori, [Entry(mountain, "main", 20), Entry(cat, "main", 40)])[0] is None
    assert companion_check(umori, base)[0].params["names"] == ["Lightning Bolt", "Savannah Lions"]
    assert companion_check(gyruda, [Entry(mountain, "main", 24), Entry(ox, "main", 36)])[0] is None
    assert companion_check(gyruda, base)[0].params["names"] == ["Lightning Bolt", "Savannah Lions"]
    # Zirda: permanents with an activated ability (basic lands have theirs), from rules text.
    issue, report = companion_check(zirda, [Entry(mountain, "main", 24), Entry(ox, "main", 36)])
    assert issue is None and report.unverified == []
    assert companion_check(zirda, base)[0].params["names"] == ["Savannah Lions"]

    # Commander: the companion stays outside the 100, within the commanders' identity;
    # Yorion never fits.
    krenko = mtg(30, "Krenko, Tin Street Kingpin", "Legendary Creature — Goblin Warrior", 3)
    krenko.attributes["color_identity"] = ["R"]
    lurrus.attributes["color_identity"] = ["W", "B"]
    edh = [Entry(krenko, "commander", 1), Entry(mountain, "main", 99)]
    issue, report = companion_check(lurrus, edh, "commander")
    # The commander is in the starting deck: a 3-mana one breaks Lurrus's condition.
    assert issue.params["names"] == ["Krenko, Tin Street Kingpin"]
    assert "color_identity" in codes(report) and "copy_limit" not in codes(report)
    small = [Entry(mtg(31, "Kiki", "Legendary Creature — Goblin", 2), "commander", 1), *edh[1:]]
    assert companion_check(lurrus, small, "commander")[0] is None
    issue = companion_check(yorion, edh, "commander")[0]
    assert issue.params == {"name": yorion.name, "rule": "yorion", "names": []}

    # Modal double-faced card: the front face counts (an instant, not a land).
    awakening = mtg(
        20,
        "Valakut Awakening // Valakut Stoneforge",
        "Instant // Land",
        3,
        layout="modal_dfc",
        faces=[
            {"name": "Valakut Awakening", "type_line": "Instant", "mana_cost": "{2}{R}"},
            {"name": "Valakut Stoneforge", "type_line": "Land"},
        ],
    )
    keruga = mtg(18, "Keruga, the Macrosage", "Legendary Creature — Dinosaur Hippo", 5)
    issue = companion_check(keruga, [Entry(mountain, "main", 56), Entry(awakening, "main", 4)])[0]
    assert issue is None
    assert companion_check(keruga, [*base])[0].params["names"] == [
        "Lightning Bolt",
        "Savannah Lions",
    ]

    # A companion this checker does not know yet.
    new = mtg(19, "New Companion", "Legendary Creature — Fox", 2, text="Companion — Something.")
    report = companion_check(new, base)[1]
    assert "companion_unknown" in {i.code for i in report.unverified}


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


def test_parse_pokemon_decklist():
    parsed = deck_import.parse(
        """Pokémon: 3
4 Charmander PAF 7
2 Charizard ex OBF 125
1 Pikachu PR-SV 27

Trainer: 2
4 Professor's Research SVI 189
Energy (1)
10 Basic {R} Energy SVE 2

Total Cards: 60
""",
        "pokemon",
    )
    assert [(line.quantity, line.name, line.section) for line in parsed.lines] == [
        (4, "Charmander", "main"),
        (2, "Charizard ex", "main"),
        (1, "Pikachu", "main"),
        (4, "Professor's Research", "main"),
        (10, "Basic Fire Energy", "main"),
    ]
    assert parsed.errors == []
    # Magic names keep a trailing word and number.
    assert deck_import.parse("1 Lightning Bolt M10 146").lines[0].name == "Lightning Bolt M10 146"


def pokemon(
    card_id: int,
    name: str,
    category: str = "Pokemon",
    stage: str | None = "Basic",
    types: tuple[str, ...] = ("fire",),
    rarity: str | None = "Common",
    legal: dict | None = None,
    **attributes,
) -> RuleCard:
    attributes = {"category": category, **({"stage": stage} if stage else {}), **attributes}
    if legal is None:
        legal = {"standard": True, "expanded": True}
    return RuleCard(
        card_id,
        name,
        attributes,
        list(types),
        [deck_rules.RulePrinting(rarity, legal or None)],
    )


def test_pokemon_standard_rules():
    charmander = pokemon(1, "Charmander")
    research = pokemon(2, "Professor's Research", "Trainer", None, (), trainerType="Supporter")
    fire = pokemon(3, "Basic Fire Energy", "Energy", None, (), energyType="Normal")
    deck = [Entry(charmander, "main", 4), Entry(research, "main", 4), Entry(fire, "main", 52)]
    report = deck_rules.check("pokemon_standard", deck)
    assert report.valid, report.issues

    # Old printing not legal, a reprint is: the card is legal.
    reprinted = pokemon(4, "Switch", "Trainer", None, (), trainerType="Item")
    reprinted.printings = [
        deck_rules.RulePrinting("Common", {"standard": False, "expanded": True}),
        deck_rules.RulePrinting("Common", {"standard": True, "expanded": True}),
    ]
    assert deck_rules.legality(reprinted, deck_rules.FORMATS["pokemon_standard"]) == "legal"

    old = pokemon(5, "Old Pikachu", legal={"standard": False, "expanded": True})
    ace = pokemon(6, "Prime Catcher", "Trainer", None, (), "ACE SPEC Rare", trainerType="Item")
    ace2 = pokemon(7, "Master Ball", "Trainer", None, (), "ACE SPEC Rare", trainerType="Item")
    radiant = pokemon(8, "Radiant Charizard", rarity="Radiant Rare")
    radiant2 = pokemon(9, "Radiant Greninja", types=("water",))
    asian = pokemon(10, "ピカチュウ", legal={})
    report = deck_rules.check(
        "pokemon_standard",
        [
            Entry(charmander, "main", 5),
            Entry(old, "main", 1),
            Entry(ace, "main", 1),
            Entry(ace2, "main", 1),
            Entry(radiant, "main", 1),
            Entry(radiant2, "main", 1),
            Entry(asian, "main", 1),
            Entry(fire, "main", 40),
            Entry(fire, "sideboard", 2),
        ],
    )
    assert codes(report) == {
        "deck_size",
        "copy_limit",
        "not_legal",
        "ace_spec_max",
        "radiant_max",
        "section_unused",
    }
    assert {i.code: i for i in report.unverified}["legality_unknown"].params["names"] == [
        "ピカチュウ"
    ]
    # Expanded: the old printing is legal there; Unlimited checks no legality.
    expanded = deck_rules.check("pokemon_expanded", [Entry(old, "main", 4), *deck[1:]])
    assert "not_legal" not in codes(expanded)
    assert "no_basic" in codes(deck_rules.check("pokemon_unlimited", deck[1:]))


def test_pokemon_glc_rules():
    charmander = pokemon(1, "Charmander")
    vulpix = pokemon(2, "Vulpix")
    squirtle = pokemon(3, "Squirtle", types=("water",))
    charizard_ex = pokemon(4, "Charizard ex", stage="Stage2")
    ace = pokemon(5, "Prime Catcher", "Trainer", None, (), "ACE SPEC Rare", trainerType="Item")
    fire = pokemon(6, "Fire Energy", "Energy", None, ())
    deck = [Entry(charmander, "main", 1), Entry(vulpix, "main", 1), Entry(fire, "main", 58)]
    report = deck_rules.check("pokemon_glc", deck)
    assert report.valid, report.issues
    assert "glc_bans" in {i.code for i in report.unverified}

    report = deck_rules.check(
        "pokemon_glc",
        [
            Entry(charmander, "main", 2),
            Entry(vulpix, "main", 1),
            Entry(squirtle, "main", 1),
            Entry(charizard_ex, "main", 1),
            Entry(ace, "main", 1),
            Entry(fire, "main", 54),
        ],
    )
    assert codes(report) == {"copy_limit", "rule_box", "single_type", "ace_spec_banned"}
    off_type = [i for i in report.issues if i.code == "single_type"]
    assert [(i.params["name"], i.params["type"]) for i in off_type] == [("Squirtle", "fire")]


async def test_allocated_copy_image(client, session, alice, catalog):
    bolt, first = catalog["Lightning Bolt"]
    card_set = await session.scalar(select(CardSet).where(CardSet.code == "TST"))
    second = Printing(
        card_id=bolt,
        set_id=card_set.id,
        external_id="bolt-2",
        collector_number="99",
        finishes=["nonfoil"],
        languages=["en"],
        image_paths={"en": "bolt-2.jpg"},
    )
    session.add(second)
    await session.flush()
    printing = await session.get(Printing, first)
    printing.image_paths = {"en": "bolt-1.jpg"}
    await session.commit()
    deck = (await new_deck(client, alice))["deck"]["id"]
    await put_card(client, alice, deck, bolt, 2)
    one = (await own(client, alice, first, 1))["item"]["id"]
    two = (await own(client, alice, second.id, 1))["item"]["id"]

    async def allocate(path, item_id):
        response = await client.post(
            f"/api/decks/{deck}/{path}",
            json={"card_id": bolt, "item_id": item_id},
            headers=alice,
        )
        assert response.status_code == 200, response.text
        return entry(response.json(), bolt)["image"]

    assert f"/printings/{second.id}/" in await allocate("allocate", two)
    await allocate("release", two)
    assert f"/printings/{first}/" in await allocate("allocate", one)
    items = (await client.get(f"/api/decks/{deck}/cards/{bolt}/items", headers=alice)).json()
    assert {i["id"]: i["image"] for i in items} == {
        one: f"/api/printings/{first}/image?lang=en",
        two: f"/api/printings/{second.id}/image?lang=en",
    }


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
    # Two items (NM, LP) to choose from: the web asks which one.
    assert entry(detail, bolt)["free_items"] == 2

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
    assert entry(other, bolt)["free_items"] == 1  # NM taken by Burn, LP left
    detail = (await allocate(izzet, 1, item_id=lp)).json()
    assert (entry(detail, bolt)["allocated"], entry(detail, bolt)["available"]) == (1, 0)
    assert entry(detail, bolt)["free_items"] == 0
    # The card page tells where each copy is.
    card = (await client.get(f"/api/cards/{bolt}", headers=alice)).json()
    assert {
        o["condition"]: [(d["name"], d["quantity"]) for d in o["decks"]]
        for p in card["printings"]
        for o in p["owned"]
    } == {"NM": [("Burn", 2)], "LP": [("Izzet", 1)]}
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


async def _second_printing(session, card_id: int, code="M10", number="146") -> int:
    card_set = CardSet(game_id="mtg", external_id=code.lower(), code=code, name=code, lang="en")
    session.add(card_set)
    await session.flush()
    printing = Printing(
        card_id=card_id,
        set_id=card_set.id,
        external_id=f"{code}-{number}",
        collector_number=number,
        finishes=["nonfoil"],
        languages=["en"],
    )
    session.add(printing)
    await session.commit()
    return printing.id


async def put_line(client, headers, deck_id, card_id, quantity, printing_id, section="main"):
    response = await client.put(
        f"/api/decks/{deck_id}/cards",
        json={
            "card_id": card_id,
            "quantity": quantity,
            "section": section,
            "printing_id": printing_id,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_printing_lines(client, session, alice, catalog):
    bolt, tst = catalog["Lightning Bolt"]
    m10 = await _second_printing(session, bolt)
    deck = (await new_deck(client, alice))["deck"]["id"]
    await put_line(client, alice, deck, bolt, 2, m10)
    await put_line(client, alice, deck, bolt, 2, tst)
    detail = await put_line(client, alice, deck, bolt, 1, None)
    card = entry(detail, bolt)
    # One card, three lines: rules and copies count them together.
    assert card["requested"] == 5 and card["quantities"] == {"main": 5}
    assert [(line["set_code"], line["quantity"]) for line in card["lines"]] == [
        ("M10", 2),
        ("TST", 2),
        (None, 1),
    ]
    assert any(i["code"] == "copy_limit" for i in detail["validation"]["issues"])

    # A printing of another card is refused.
    other = catalog["Shock"][1]
    refused = await client.put(
        f"/api/decks/{deck}/cards",
        json={"card_id": bolt, "quantity": 1, "printing_id": other},
        headers=alice,
    )
    assert refused.status_code == 404

    # Allocating takes the printings lines ask for first, then any.
    await own(client, alice, tst, 3)
    await own(client, alice, m10, 1)
    allocated = await client.post(
        f"/api/decks/{deck}/allocate", json={"card_id": bolt, "quantity": 3}, headers=alice
    )
    assert allocated.status_code == 200, allocated.text
    lines = entry(allocated.json(), bolt)["lines"]
    assert [(line["set_code"], line["allocated"]) for line in lines] == [
        ("M10", 1),
        ("TST", 2),
        (None, 0),
    ]
    assert lines[0]["available"] == 0 and lines[1]["available"] == 1

    # Moving the "any" line to M10, then one TST copy to any.
    moved = await client.post(
        f"/api/decks/{deck}/cards/move",
        json={"card_id": bolt, "printing_id": None, "to_printing_id": m10},
        headers=alice,
    )
    assert moved.status_code == 200, moved.text
    moved = await client.post(
        f"/api/decks/{deck}/cards/move",
        json={"card_id": bolt, "printing_id": tst, "to_printing_id": None, "quantity": 1},
        headers=alice,
    )
    lines = entry(moved.json(), bolt)["lines"]
    assert [(line["set_code"], line["quantity"]) for line in lines] == [
        ("M10", 3),
        ("TST", 1),
        (None, 1),
    ]
    assert entry(moved.json(), bolt)["allocated"] == 3

    # Printings of the card for the chooser, with the user's copies.
    printings = await client.get(f"/api/decks/{deck}/cards/{bolt}/printings", headers=alice)
    assert {p["set_code"]: (p["owned"], p["available"]) for p in printings.json()} == {
        "M10": (1, 0),
        "TST": (3, 1),
    }

    # A catalog merge moves the lines to the new printing (added to its line).
    from app.services.catalog import CatalogWriter

    writer = CatalogWriter(session, "mtg")
    await writer._move_items(m10, tst)
    await session.commit()
    detail = (await client.get(f"/api/decks/{deck}", headers=alice)).json()
    lines = entry(detail, bolt)["lines"]
    assert [(line["set_code"], line["quantity"]) for line in lines] == [("TST", 4), (None, 1)]


async def test_printing_line_falls_back_to_any(client, session, alice, catalog):
    bolt, _ = catalog["Lightning Bolt"]
    m10 = await _second_printing(session, bolt)
    deck = (await new_deck(client, alice))["deck"]["id"]
    await put_line(client, alice, deck, bolt, 2, m10)
    await session.execute(Printing.__table__.delete().where(Printing.id == m10))
    await session.commit()
    detail = (await client.get(f"/api/decks/{deck}", headers=alice)).json()
    assert [(line["printing_id"], line["quantity"]) for line in entry(detail, bolt)["lines"]] == [
        (None, 2)
    ]


async def test_import_keeps_printings(client, session, alice, catalog):
    bolt, _ = catalog["Lightning Bolt"]
    m10 = await _second_printing(session, bolt)
    text = "4 Lightning Bolt (M10) 146\n2 Lightning Bolt (XXX) 1\n1 Shock [TST]\n"
    preview = await client.post("/api/decks/import/preview", json={"text": text}, headers=alice)
    lines = preview.json()["lines"]
    assert [(line["set_code"], line["collector_number"]) for line in lines] == [
        ("M10", "146"),
        ("XXX", "1"),
        ("TST", None),
    ]
    assert lines[0]["printing"]["id"] == m10
    # Unknown set: any printing.
    assert lines[1]["printing"] is None
    assert lines[2]["printing"]["id"] == catalog["Shock"][1]
    deck = (await new_deck(client, alice))["deck"]["id"]
    entries = [
        {
            "card_id": line["card"]["card_id"],
            "quantity": line["quantity"],
            "printing_id": line["printing"] and line["printing"]["id"],
        }
        for line in lines
    ]
    imported = await client.post(
        f"/api/decks/{deck}/import", json={"entries": entries}, headers=alice
    )
    assert imported.status_code == 200, imported.text
    lines = entry(imported.json(), bolt)["lines"]
    assert [(line["set_code"], line["quantity"]) for line in lines] == [("M10", 4), (None, 2)]


def _lorcana(card_id, name, inks, legal=None, **attributes):
    if legal is not None:
        attributes["legalities"] = legal
    return RuleCard(card_id, name, attributes, inks)


def test_lorcana_rules():
    core = {"core": "legal", "infinity": "legal"}
    elsa = _lorcana(1, "Elsa - Snow Queen", ["amethyst"], core)
    mickey = _lorcana(2, "Mickey Mouse - Wayward Sorcerer", ["amethyst"], core)
    puppy = _lorcana(3, "Dalmatian Puppy - Tail Wagger", ["sapphire"], core, max_copies=99)
    rotated = _lorcana(
        4, "Ariel - On Human Legs", ["sapphire"], {"core": "not_legal", "infinity": "legal"}
    )
    banned = _lorcana(
        5, "Hiram Flaversham - Toymaker", ["sapphire"], {"core": "legal", "infinity": "banned"}
    )
    dual = _lorcana(6, "Rhino - Motivational Speaker", ["amethyst", "sapphire"], core)
    ruby = _lorcana(7, "Maui - Hero to All", ["ruby"], core)

    def codes(fmt, entries):
        report = deck_rules.check(fmt, entries)
        return {i.code for i in report.issues}, report

    found, _ = codes(
        "lorcana_core",
        [
            Entry(elsa, "main", 4),
            Entry(mickey, "main", 4),
            Entry(puppy, "main", 50),
            Entry(dual, "main", 2),
        ],
    )
    assert found == set()
    found, report = codes("lorcana_core", [Entry(elsa, "main", 5), Entry(rotated, "main", 4)])
    assert found == {"deck_size_min", "copy_limit", "not_legal"}
    found, _ = codes("lorcana_infinity", [Entry(rotated, "main", 4), Entry(banned, "main", 1)])
    assert found == {"deck_size_min", "banned"}
    # Three inks: the two most played stay, the others are off ink.
    found, report = codes(
        "lorcana_unrestricted",
        [
            Entry(elsa, "main", 4),
            Entry(puppy, "main", 56),
            Entry(ruby, "main", 1),
            Entry(banned, "main", 1),
        ],
    )
    assert found == {"inks_max", "off_ink"}
    assert [i.params["name"] for i in report.issues if i.code == "off_ink"] == [
        "Maui - Hero to All"
    ]
    # Unknown legality is listed, not an error.
    unknown = _lorcana(8, "Stitch - New Dog", ["amber"])
    found, report = codes("lorcana_core", [Entry(unknown, "main", 60)])
    assert "legality_unknown" in {i.code for i in report.unverified}
    assert deck_rules.GAMES["lorcana"] == (
        "lorcana_core",
        "lorcana_infinity",
        "lorcana_unrestricted",
    )


async def test_export_and_import_back(client, session, alice, catalog):
    bolt, tst = catalog["Lightning Bolt"]
    krenko = catalog["Krenko, Mob Boss"][0]
    m10 = await _second_printing(session, bolt)
    deck = (await new_deck(client, alice, "Goblins: v2", "commander"))["deck"]["id"]
    await put_card(client, alice, deck, krenko, 1, "commander")
    await put_line(client, alice, deck, bolt, 2, m10)
    await put_line(client, alice, deck, bolt, 2, None)
    await put_card(client, alice, deck, catalog["Shock"][0], 1, "sideboard")
    # One "any" copy allocated from TST: exported with that printing.
    await own(client, alice, tst, 1)
    await client.post(
        f"/api/decks/{deck}/allocate", json={"card_id": bolt, "quantity": 1}, headers=alice
    )
    exported = await client.get(f"/api/decks/{deck}/export", headers=alice)
    assert exported.status_code == 200, exported.text
    assert exported.json()["filename"] == "Goblins_ v2.txt"
    text = exported.json()["text"]
    # Magic lines of any printing with no copy allocated keep no set.
    assert text == (
        "Commander\n1 Krenko, Mob Boss\n\n"
        "Deck\n2 Lightning Bolt (M10) 146\n1 Lightning Bolt (TST) 0\n1 Lightning Bolt\n\n"
        "Sideboard\n1 Shock\n"
    )
    plain = await client.get(f"/api/decks/{deck}/export?sets=false", headers=alice)
    assert plain.json()["text"] == (
        "Commander\n1 Krenko, Mob Boss\n\nDeck\n4 Lightning Bolt\n\nSideboard\n1 Shock\n"
    )
    # Read back: same cards, sections and printings.
    preview = await client.post("/api/decks/import/preview", json={"text": text}, headers=alice)
    lines = preview.json()["lines"]
    assert all(line["status"] == "resolved" for line in lines)
    assert [(line["section"], line["printing"] and line["printing"]["id"]) for line in lines] == [
        ("commander", None),
        ("main", m10),
        ("main", tst),
        ("main", None),
        ("sideboard", None),
    ]


def test_export_formats():
    from app.services.deck_export import ExportLine, export_text

    pokemon = [
        ExportLine("Charmander", "main", "Pokémon", 4, "PAF", "7"),
        ExportLine("Professor's Research", "main", "Supporter", 4, "SVI", "189"),
        ExportLine("Basic Fire Energy", "main", "Energy", 52, "SVE", "2"),
    ]
    assert export_text("pokemon", pokemon) == (
        "Pokémon: 4\n4 Charmander PAF 7\n\n"
        "Trainer: 4\n4 Professor's Research SVI 189\n\n"
        "Energy: 52\n52 Basic Fire Energy SVE 2\n\n"
        "Total Cards: 60\n"
    )
    parsed = deck_import.parse(export_text("pokemon", pokemon), "pokemon")
    assert [(line.quantity, line.name, line.set_code) for line in parsed.lines] == [
        (4, "Charmander", "PAF"),
        (4, "Professor's Research", "SVI"),
        (52, "Basic Fire Energy", "SVE"),
    ]
    lorcana = [ExportLine("Elsa - Snow Queen", "main", "Character", 4, "1", "41")]
    assert export_text("lorcana", lorcana) == "4 Elsa - Snow Queen\n"
    assert deck_import.parse("4 Elsa - Snow Queen\n", "lorcana").lines[0].name == (
        "Elsa - Snow Queen"
    )
    # Magic: the companion has its own block (MTG Arena's), read back to its section.
    magic = [
        ExportLine("Lurrus of the Dream-Den", "companion", "Creature", 1, "IKO", "226"),
        ExportLine("Lightning Bolt", "main", "Instant", 4, "M10", "146"),
        ExportLine("Duress", "sideboard", "Sorcery", 2),
    ]
    text = export_text("mtg", magic)
    assert text.startswith("Companion\n1 Lurrus of the Dream-Den (IKO) 226\n\nDeck\n")
    parsed = deck_import.parse(text)
    assert [line.section for line in parsed.lines] == ["companion", "main", "sideboard"]


async def test_lorcana_deck(client, session, alice):
    card_set = CardSet(game_id="lorcana", external_id="1", code="1", name="The First Chapter")
    session.add(card_set)
    await session.flush()
    elsa = Card(
        game_id="lorcana",
        external_id="elsa - snow queen",
        name="Elsa - Snow Queen",
        colors=["amethyst"],
        attributes={
            "type": "Character",
            "classifications": ["Floodborn", "Hero", "Queen", "Sorcerer"],
            "cost": 6,
            "legalities": {"core": "not_legal", "infinity": "legal"},
        },
    )
    song = Card(
        game_id="lorcana",
        external_id="friends on the other side",
        name="Friends on the Other Side",
        colors=["amethyst"],
        attributes={"type": "Action", "classifications": ["Song"], "cost": 3},
    )
    session.add_all([elsa, song])
    await session.flush()
    for number, card in enumerate((elsa, song), start=41):
        printing = Printing(card_id=card.id, set_id=card_set.id, external_id=str(number))
        printing.collector_number, printing.finishes = str(number), ["normal"]
        printing.languages = ["en"]
        session.add(printing)
        session.add(CardName(card_id=card.id, lang="en", name=card.name))
    await session.commit()
    created = await client.post(
        "/api/decks",
        json={"name": "Elsa", "game_id": "lorcana", "format": "lorcana_core"},
        headers=alice,
    )
    assert created.status_code == 201, created.text
    deck = created.json()["deck"]["id"]
    wrong = await client.post(
        "/api/decks", json={"name": "x", "game_id": "lorcana", "format": "standard"}, headers=alice
    )
    assert wrong.status_code == 422
    await put_card(client, alice, deck, elsa.id, 4)
    detail = await put_card(client, alice, deck, song.id, 2)
    assert detail["groups"] == ["Character", "Action", "Song", "Item", "Location", "Other"]
    assert {e["name"]: (e["group"], e["type_line"]) for e in detail["entries"]} == {
        "Elsa - Snow Queen": ("Character", "Character — Floodborn, Hero, Queen, Sorcerer — 6 ink"),
        "Friends on the Other Side": ("Song", "Action — Song — 3 ink"),
    }
    issues = {i["code"] for i in detail["validation"]["issues"]}
    assert issues == {"deck_size_min", "not_legal"}
    assert {i["code"] for i in detail["validation"]["unverified"]} == {"legality_unknown"}
    exported = (await client.get(f"/api/decks/{deck}/export", headers=alice)).json()["text"]
    assert exported == "4 Elsa - Snow Queen\n2 Friends on the Other Side\n"
    preview = await client.post(
        "/api/decks/import/preview", json={"text": exported, "game_id": "lorcana"}, headers=alice
    )
    assert [line["card"]["card_id"] for line in preview.json()["lines"]] == [elsa.id, song.id]


async def test_card_search_owned_filter(client, alice, catalog):
    bolt, printing = catalog["Lightning Bolt"]
    await own(client, alice, printing, 2)
    found = await client.get("/api/cards", params={"game": "mtg", "owned": True}, headers=alice)
    assert [(c["id"], c["owned_copies"]) for c in found.json()["items"]] == [(bolt, 2)]
    every = await client.get("/api/cards", params={"game": "mtg", "q": "shock"}, headers=alice)
    assert every.json()["items"][0]["owned_copies"] == 0


def test_parse_set_suffixes():
    parsed = deck_import.parse("4 Lightning Bolt (M10) 146 *F*\n1 Shock (M19)\n2 Jolt [M19]\n")
    assert [(line.name, line.set_code, line.collector_number) for line in parsed.lines] == [
        ("Lightning Bolt", "M10", "146"),
        ("Shock", "M19", None),
        ("Jolt", "M19", None),
    ]
    parsed = deck_import.parse("4 Charmander PAF 7\n", "pokemon")
    line = parsed.lines[0]
    assert (line.name, line.set_code, line.collector_number) == ("Charmander", "PAF", "7")


def test_magic_group_by_front_face():
    from app.api.decks import _group

    def card(type_line: str, faces: list[str] | None = None) -> Card:
        types = [t for part in type_line.split(" // ") for t in part.split("—")[0].split()]
        attributes = {"types": types, "type_line": type_line}
        if faces:
            attributes["faces"] = [{"type_line": f} for f in faces]
        return Card(game_id="mtg", external_id=type_line, name=type_line, attributes=attributes)

    # Modal double-faced spells with a land back are spells, not lands.
    assert _group(card("Instant // Land", ["Instant", "Land"])) == "Instant"
    assert _group(card("Sorcery // Land")) == "Sorcery"
    assert _group(card("Legendary Creature — God // Legendary Land")) == "Creature"
    # A land front stays a land; artifact lands too, land creatures are creatures.
    assert _group(card("Land // Land", ["Land", "Land"])) == "Land"
    assert _group(card("Artifact Land")) == "Land"
    assert _group(card("Land Creature — Forest Dryad")) == "Creature"


async def test_double_faced_cards_show_their_back(client, session, alice, catalog):
    delver, printing_id = catalog["Delver of Secrets // Insectile Aberration"]
    bolt, _ = catalog["Lightning Bolt"]
    printing = await session.get(Printing, printing_id)
    printing.attributes = {**printing.attributes, "back_image_url": "https://example.test/b.jpg"}
    printing.image_urls = {"en": "https://example.test/f.jpg"}
    await session.commit()
    deck = (await new_deck(client, alice))["deck"]["id"]
    await put_card(client, alice, deck, bolt, 1)
    response = await client.put(
        f"/api/decks/{deck}/cards",
        json={"card_id": delver, "quantity": 2, "section": "main", "printing_id": printing_id},
        headers=alice,
    )
    detail = response.json()
    back = f"/api/printings/{printing_id}/image?face=back"
    assert entry(detail, delver)["back_image"] == back
    assert entry(detail, delver)["lines"][0]["back_image"] == back
    assert entry(detail, bolt)["back_image"] is None
