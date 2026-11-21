"""Decks of Riftbound, Yu-Gi-Oh! (TCG and OCG) and Sorcery: format rules, sections,
import and export."""

from app.models import Card, CardName, CardSet, Printing
from app.services import deck_import, deck_rules
from app.services.deck_export import ExportLine, export_text
from app.services.deck_rules import FORMATS, Entry, RuleCard
from tests.test_decks import alice, catalog, entry, put_card  # noqa: F401 (fixtures)


def _codes(fmt: str, entries: list[Entry]) -> tuple[set[str], deck_rules.Report]:
    report = deck_rules.check(fmt, entries)
    return {i.code for i in report.issues}, report


def _rb(card_id, name, kind, domains=(), supertype=None, tags=()):
    attributes = {
        "type": kind,
        "supertype": supertype,
        "domains": list(domains),
        "tags": list(tags),
    }
    return RuleCard(card_id, name, attributes, list(domains) or ["colorless"])


def test_riftbound_rules():
    legend = _rb(1, "Ahri, Nine-Tailed Fox", "Legend", ["calm", "mind"], tags=["Ahri"])
    champion = _rb(2, "Ahri, Alluring", "Unit", ["calm"], "Champion", ["Ahri", "Ionia"])
    other_champion = _rb(3, "Jinx, Demolitionist", "Unit", ["fury"], "Champion", ["Jinx"])
    unit = _rb(4, "Calm Rune Keeper", "Unit", ["calm"])
    spell = _rb(5, "Mind Spark", "Spell", ["mind"])
    gear = _rb(6, "Doran's Blade", "Gear")
    fury = _rb(7, "Fury Bolt", "Spell", ["fury"])
    calm_rune = _rb(8, "Calm Rune", "Rune", ["calm"])
    mind_rune = _rb(9, "Mind Rune", "Rune", ["mind"])
    # Some sources list colorless cards with a "colorless" domain: they fit any legend.
    fields = [_rb(10 + i, f"Battlefield {i}", "Battlefield", ["colorless"]) for i in range(3)]
    deck = [
        Entry(legend, "legend", 1),
        Entry(champion, "champion", 1),
        Entry(champion, "main", 2),
        *(Entry(_rb(20 + i, f"Unit {i}", "Unit", ["calm"]), "main", 3) for i in range(11)),
        Entry(spell, "main", 3),
        Entry(gear, "main", 1),
        Entry(calm_rune, "runes", 6),
        Entry(mind_rune, "runes", 6),
        *(Entry(f, "battlefields", 1) for f in fields),
        Entry(unit, "sideboard", 3),
    ]
    found, report = _codes("riftbound_constructed", deck)
    assert found == set(), report.issues
    assert "bans_unchecked" in {i.code for i in report.unverified}

    found, report = _codes(
        "riftbound_constructed",
        [
            Entry(legend, "legend", 1),
            Entry(other_champion, "champion", 1),
            Entry(champion, "main", 3),
            Entry(fury, "main", 1),
            Entry(calm_rune, "main", 1),
            Entry(mind_rune, "runes", 11),
            Entry(fields[0], "battlefields", 2),
            Entry(unit, "sideboard", 9),
        ],
    )
    assert found == {
        "section_size_min",  # main deck
        "section_size_exact",  # runes, battlefields
        "section_size_max",  # sideboard
        "copy_limit",  # 9 copies of a unit in the sideboard
        "champion_tag",
        "wrong_section",  # a rune in the main deck
        "battlefield_duplicate",
        "off_domain",  # Fury cards
    }
    assert {i.params["name"] for i in report.issues if i.code == "off_domain"} == {
        "Jinx, Demolitionist",
        "Fury Bolt",
    }
    # Copies by name include the champion and the sideboard.
    found, _ = _codes(
        "riftbound_constructed",
        [Entry(legend, "legend", 1), Entry(champion, "champion", 1), Entry(champion, "main", 3)],
    )
    assert "copy_limit" in found
    # No legend: that is the issue, no extra note about domains.
    found, report = _codes("riftbound_constructed", [Entry(unit, "main", 40)])
    assert "section_size_exact" in found
    assert {i.code for i in report.unverified} == {"bans_unchecked"}


def _yg(card_id, name, frame, banlist=None, tcg=True, ocg=True):
    attributes = {"frame": frame, "banlist": banlist or {}}
    if tcg:
        attributes["tcg_date"] = "2002-03-08"
    if ocg:
        attributes["ocg_date"] = "1999-02-04"
    return RuleCard(card_id, name, attributes)


def test_yugioh_rules():
    monster = _yg(1, "Dark Magician", "normal")
    pot = _yg(2, "Pot of Greed", "spell", {"tcg": "Forbidden", "ocg": "Forbidden"})
    limited = _yg(3, "Monster Reborn", "spell", {"tcg": "Limited", "ocg": "Semi-Limited"})
    fusion = _yg(4, "Dark Paladin", "fusion")
    xyz_pendulum = _yg(5, "Odd-Eyes Rebellion Dragon", "xyz_pendulum")
    trap = _yg(6, "Mirror Force", "trap")
    ocg_only = _yg(7, "OCG Exclusive", "effect", tcg=False)
    token = _yg(8, "Sheep Token", "token")
    base = [
        Entry(monster, "main", 3),
        *(Entry(_yg(10 + i, f"M{i}", "effect"), "main", 3) for i in range(12)),
        Entry(trap, "main", 1),
    ]
    assert sum(e.quantity for e in base) == 40

    found, report = _codes(
        "yugioh_advanced", [*base, Entry(fusion, "extra", 2), Entry(xyz_pendulum, "extra", 1)]
    )
    assert found == set(), report.issues
    found, report = _codes(
        "yugioh_advanced",
        [
            *base,
            Entry(pot, "main", 1),
            Entry(limited, "main", 2),
            Entry(fusion, "main", 1),
            Entry(trap, "extra", 1),
            Entry(ocg_only, "sideboard", 1),
            Entry(token, "main", 1),
        ],
    )
    assert found == {"banned", "copy_limit", "wrong_section", "not_legal", "not_playable"}
    assert [i.params["limit"] for i in report.issues if i.code == "copy_limit"] == [1]
    # OCG list: Semi-Limited allows two; the OCG-only card is legal there.
    found, _ = _codes(
        "ocg_advanced", [*base, Entry(limited, "main", 2), Entry(ocg_only, "sideboard", 1)]
    )
    assert found == set()
    # Traditional: forbidden cards are limited to one.
    found, _ = _codes("yugioh_traditional", [*base, Entry(pot, "main", 1)])
    assert found == set()
    found, _ = _codes("yugioh_traditional", [*base, Entry(pot, "main", 2)])
    assert found == {"copy_limit"}
    # Sizes: 40 to 60 main, 15 extra and side at most.
    found, _ = _codes(
        "yugioh_unrestricted",
        [Entry(monster, "main", 3), Entry(fusion, "extra", 16), Entry(trap, "sideboard", 16)],
    )
    assert found == {"section_size_min", "section_size_max", "copy_limit"}
    # Cards of a catalog not synced again: ban list not known.
    old = RuleCard(9, "Old Card", {"frame": "effect"})
    _, report = _codes("yugioh_advanced", [*base, Entry(old, "main", 1)])
    assert "legality_unknown" in {i.code for i in report.unverified}
    assert deck_rules.legality(old, FORMATS["yugioh_unrestricted"]) == "legal"
    # OCG-only cards (YGOJSON): Extra Deck kind from their classifications.
    ygojson = RuleCard(10, "Link", {"card_type": "monster", "classifications": ["link"]})
    assert deck_rules.is_extra_deck(ygojson)


def _so(card_id, name, category, kind, rarity="Ordinary"):
    return RuleCard(card_id, name, {"category": category, "type": kind, "rarity": rarity})


def test_sorcery_rules():
    avatar = _so(1, "Sparkmage", "Avatar", "Avatar", None)
    site = _so(2, "Arid Desert", "Site", "Site")
    unique_site = _so(3, "Avalon", "Site", "Site", "Unique")
    minion = _so(4, "Pudge Butcher", "Spell", "Minion")
    elite = _so(5, "Lord of the Void", "Spell", "Minion", "Elite")
    magic = _so(6, "Fireball", "Spell", "Magic", "Exceptional")
    deck = [
        Entry(avatar, "avatar", 1),
        *(Entry(_so(10 + i, f"Site {i}", "Site", "Site"), "atlas", 4) for i in range(7)),
        Entry(site, "atlas", 2),
        *(Entry(_so(30 + i, f"Spell {i}", "Spell", "Minion"), "main", 4) for i in range(14)),
        Entry(elite, "main", 2),
        Entry(magic, "main", 2),
        Entry(minion, "sideboard", 4),
    ]
    found, report = _codes("sorcery_constructed", deck)
    assert found == set(), report.issues
    found, report = _codes(
        "sorcery_constructed",
        [
            Entry(avatar, "avatar", 2),
            Entry(unique_site, "atlas", 2),
            Entry(site, "main", 1),
            Entry(elite, "main", 3),
            Entry(magic, "sideboard", 11),
        ],
    )
    assert found == {
        "section_size_exact",  # two avatars
        "section_size_min",  # atlas, spellbook
        "section_size_max",  # collection (a warning)
        "wrong_section",  # a site in the spellbook
        "copy_limit",
    }
    assert {
        i.params["name"]: i.params["limit"] for i in report.issues if i.code == "copy_limit"
    } == {
        "Avalon": 1,
        "Lord of the Void": 2,
        "Fireball": 3,
    }
    assert [i.level for i in report.issues if i.code == "section_size_max"] == ["warning"]


def test_home_sections():
    rift = FORMATS["riftbound_constructed"]
    assert deck_rules.home_section(rift, {"type": "Rune"}) == "runes"
    assert deck_rules.home_section(rift, {"type": "Legend"}, "sideboard") == "legend"
    assert deck_rules.home_section(rift, {"type": "Battlefield"}, "sideboard") == "sideboard"
    assert deck_rules.home_section(rift, {"type": "Unit"}) == "main"
    assert deck_rules.home_section(rift, {"type": "Rune"}, "champion") == "champion"
    ygo = FORMATS["yugioh_advanced"]
    assert deck_rules.home_section(ygo, {"frame": "synchro"}) == "extra"
    assert deck_rules.home_section(ygo, {"frame": "synchro"}, "sideboard") == "sideboard"
    assert deck_rules.home_section(ygo, {"frame": "effect"}) == "main"
    sorcery = FORMATS["sorcery_constructed"]
    assert deck_rules.home_section(sorcery, {"category": "Site", "type": "Site"}) == "atlas"
    assert deck_rules.home_section(sorcery, {"category": "Avatar"}) == "avatar"
    assert deck_rules.home_section(FORMATS["standard"], {"types": ["Land"]}) == "main"


def test_parse_and_export_sections():
    ydk = "#created by someone\n#main\n46986414\n46986414\n#extra\n40737112\n!side\n44095762\n"
    parsed = deck_import.parse(ydk, "yugioh")
    assert [(line.name, line.section) for line in parsed.lines] == [
        ("46986414", "main"),
        ("46986414", "main"),
        ("40737112", "extra"),
        ("44095762", "sideboard"),
    ]
    lines = [
        ExportLine("Ahri, Nine-Tailed Fox", "legend", "Legend", 1),
        ExportLine("Ahri, Alluring", "champion", "Unit", 1),
        ExportLine("Calm Rune Keeper", "main", "Unit", 3, "OGN", "12"),
        ExportLine("Zaun Warrens", "battlefields", "Battlefield", 1),
        ExportLine("Calm Rune", "runes", "Rune", 12),
        ExportLine("Fury Bolt", "sideboard", "Spell", 2),
    ]
    text = export_text("riftbound", lines)
    assert text == (
        "Legend:\n1 Ahri, Nine-Tailed Fox\n\nChampion:\n1 Ahri, Alluring\n\n"
        "Main Deck:\n3 Calm Rune Keeper (OGN) 12\n\nBattlefields:\n1 Zaun Warrens\n\n"
        "Runes:\n12 Calm Rune\n\nSideboard:\n2 Fury Bolt\n"
    )
    back = deck_import.parse(text, "riftbound")
    assert [line.section for line in back.lines] == [
        "legend",
        "champion",
        "main",
        "battlefields",
        "runes",
        "sideboard",
    ]
    assert (
        export_text(
            "yugioh-ocg",
            [
                ExportLine("Dark Magician", "main", "Monster", 3),
                ExportLine("Dark Paladin", "extra", "Fusion", 1),
            ],
        )
        == "Main Deck:\n3 Dark Magician\n\nExtra Deck:\n1 Dark Paladin\n"
    )
    sorcery = export_text(
        "sorcery",
        [
            ExportLine("Sparkmage", "avatar", "Avatar", 1),
            ExportLine("Arid Desert", "atlas", "Site", 4),
            ExportLine("Fireball", "main", "Magic", 3),
            ExportLine("Pudge Butcher", "sideboard", "Minion", 1),
        ],
    )
    assert [line.section for line in deck_import.parse(sorcery, "sorcery").lines] == [
        "avatar",
        "atlas",
        "main",
        "sideboard",
    ]


async def test_yugioh_deck(client, session, alice):  # noqa: F811 (fixture)
    card_set = CardSet(game_id="yugioh", external_id="LOB", code="LOB", name="Legend of Blue Eyes")
    session.add(card_set)
    await session.flush()
    banlist = {"tcg_date": "2002-03-08", "ocg_date": "1999-02-04"}
    dm = Card(
        game_id="yugioh",
        external_id="46986414",
        name="Dark Magician",
        colors=["dark"],
        attributes={
            "frame": "normal",
            "type": "Normal Monster",
            "race": "Spellcaster",
            "level": 7,
            "banlist": {},
            **banlist,
        },
    )
    paladin = Card(
        game_id="yugioh",
        external_id="98502113",
        name="Dark Paladin",
        colors=["dark"],
        attributes={
            "frame": "fusion",
            "type": "Fusion Monster",
            "race": "Spellcaster",
            "level": 8,
            "banlist": {},
            **banlist,
        },
    )
    pot = Card(
        game_id="yugioh",
        external_id="55144522",
        name="Pot of Greed",
        colors=["spell"],
        attributes={
            "frame": "spell",
            "type": "Spell Card",
            "race": "Normal",
            "banlist": {"tcg": "Forbidden"},
            **banlist,
        },
    )
    session.add_all([dm, paladin, pot])
    await session.flush()
    for number, card in enumerate((dm, paladin, pot), start=1):
        printing = Printing(card_id=card.id, set_id=card_set.id, external_id=f"LOB-{number:03}")
        printing.collector_number, printing.finishes = f"LOB-{number:03}", ["normal"]
        printing.languages = ["en"]
        session.add(printing)
        session.add(CardName(card_id=card.id, lang="en", name=card.name))
    await session.commit()

    formats = (await client.get("/api/decks/formats", headers=alice)).json()
    ygo = next(g for g in formats if g["game_id"] == "yugioh")
    advanced = ygo["formats"][0]
    assert advanced["id"] == "yugioh_advanced"
    assert [(s["id"], s["name"]) for s in advanced["sections"]] == [
        ("main", "Main Deck"),
        ("extra", "Extra Deck"),
        ("sideboard", "Side Deck"),
    ]
    assert advanced["counted"] == ["main"]
    assert [f["id"] for g in formats if g["game_id"] == "yugioh-ocg" for f in g["formats"]] == [
        "ocg_advanced",
        "ocg_traditional",
        "ocg_unrestricted",
    ]

    created = await client.post(
        "/api/decks",
        json={"name": "Magicians", "game_id": "yugioh", "format": "yugioh_advanced"},
        headers=alice,
    )
    assert created.status_code == 201, created.text
    deck = created.json()["deck"]["id"]
    await put_card(client, alice, deck, dm.id, 3)
    # No section: a fusion monster goes to the Extra Deck; `add` adds to its line.
    for _ in range(2):
        added = await client.put(
            f"/api/decks/{deck}/cards",
            json={"card_id": paladin.id, "quantity": 1, "add": True},
            headers=alice,
        )
        assert added.status_code == 200, added.text
    assert entry(added.json(), paladin.id)["quantities"] == {"extra": 2}
    await put_card(client, alice, deck, paladin.id, 1, "extra")
    detail = await put_card(client, alice, deck, pot.id, 1)
    assert detail["deck"]["card_count"] == 4
    assert detail["deck"]["counts"] == {"main": 4, "extra": 1}
    assert {
        e["name"]: (e["group"], e["quantities"], e["type_line"]) for e in detail["entries"]
    } == {
        "Dark Magician": ("Monster", {"main": 3}, "Normal Monster — Spellcaster — Level 7"),
        "Dark Paladin": ("Fusion", {"extra": 1}, "Fusion Monster — Spellcaster — Level 8"),
        "Pot of Greed": ("Spell", {"main": 1}, "Spell Card — Normal"),
    }
    assert {i["code"] for i in detail["validation"]["issues"]} == {"section_size_min", "banned"}
    assert next(e for e in detail["entries"] if e["name"] == "Pot of Greed")["legal"] == "banned"

    exported = (await client.get(f"/api/decks/{deck}/export?sets=false", headers=alice)).json()
    assert exported["text"] == (
        "Main Deck:\n3 Dark Magician\n1 Pot of Greed\n\nExtra Deck:\n1 Dark Paladin\n"
    )
    # A YDK file: passwords (leading zeros dropped), the fusion put back in the Extra Deck.
    preview = await client.post(
        "/api/decks/import/preview",
        json={"text": "#main\n046986414\n98502113\n!side\n55144522\n", "game_id": "yugioh"},
        headers=alice,
    )
    assert [(line["card"]["card_id"], line["section"]) for line in preview.json()["lines"]] == [
        (dm.id, "main"),
        (paladin.id, "extra"),
        (pot.id, "sideboard"),
    ]
