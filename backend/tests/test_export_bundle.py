"""Export bundles: cards, followed sets and decks in one zip, imported back."""

import csv
import io
import json
import zipfile

from sqlalchemy import func, select

from app.models import BinderSet, CollectionItem, Deck, DeckAllocation, DeckCard
from app.services import export_bundle
from tests.conftest import bearer, make_user
from tests.test_decks import catalog, own  # noqa: F401 (fixture)


async def with_modules(client, session, username: str, modules: list[str]) -> dict:
    await make_user(session, username)
    headers = await bearer(client, username)
    response = await client.patch("/api/auth/me", json={"modules": modules}, headers=headers)
    assert response.status_code == 200, response.text
    return headers


async def upload(client, headers, data: bytes, name="zukan.zip", **params):
    return await client.post(
        "/api/collection/import",
        params=params,
        files={"file": (name, data, "application/zip")},
        headers=headers,
    )


def bundle(files: dict[str, str]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return out.getvalue()


def rows(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(archive.read(name).decode())))


async def snapshot(session, user_id: int):
    session.expire_all()
    items = await session.scalar(
        select(func.sum(CollectionItem.quantity)).where(CollectionItem.user_id == user_id)
    )
    followed = await session.scalar(
        select(func.count()).select_from(BinderSet).where(BinderSet.user_id == user_id)
    )
    lines = await session.scalar(
        select(func.sum(DeckCard.quantity)).join(Deck).where(Deck.user_id == user_id)
    )
    allocated = await session.scalar(
        select(func.sum(DeckAllocation.quantity)).join(Deck).where(Deck.user_id == user_id)
    )
    return items or 0, followed, lines or 0, allocated or 0


async def alice_bundle(client, session, catalog) -> tuple[dict, bytes]:  # noqa: F811
    alice = await with_modules(client, session, "alice", ["binder", "decks"])
    bolt, bolt_printing = catalog["Lightning Bolt"]
    await own(client, alice, bolt_printing, 3)
    card_set = (await client.get("/api/games/mtg/sets", headers=alice)).json()[0]
    followed = await client.post(
        "/api/binder", json={"set_id": card_set["id"], "finish": "foil"}, headers=alice
    )
    assert followed.status_code == 201, followed.text
    deck = (
        await client.post("/api/decks", json={"name": "Burn", "format": "standard"}, headers=alice)
    ).json()["deck"]["id"]
    put = await client.put(
        f"/api/decks/{deck}/cards", json={"card_id": bolt, "quantity": 4}, headers=alice
    )
    assert put.status_code == 200, put.text
    allocated = await client.post(
        f"/api/decks/{deck}/allocate", json={"card_id": bolt, "quantity": 2}, headers=alice
    )
    assert allocated.status_code == 200, allocated.text
    response = await client.get("/api/collection/export", params={"parts": "all"}, headers=alice)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    return alice, response.content


async def test_bundle_round_trip(client, session, catalog):  # noqa: F811
    alice, data = await alice_bundle(client, session, catalog)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert sorted(archive.namelist()) == [
            "binder_sets.csv",
            "cards.csv",
            "deck_allocations.csv",
            "deck_cards.csv",
            "decks.csv",
            "manifest.json",
        ]
        manifest = json.loads(archive.read("manifest.json"))
        assert (manifest["format"], manifest["parts"]) == (
            "zukan-export",
            ["cards", "binder", "decks"],
        )
        followed = rows(archive, "binder_sets.csv")
        assert [(r["game"], r["set_id"], r["finish"]) for r in followed] == [("mtg", "tst", "foil")]
        assert [(r["deck"], r["name"], r["format"]) for r in rows(archive, "decks.csv")] == [
            ("1", "Burn", "standard")
        ]
        lines = rows(archive, "deck_cards.csv")
        assert [(r["card_id"], r["section"], r["quantity"]) for r in lines] == [
            ("Lightning Bolt", "main", "4")
        ]
        allocations = rows(archive, "deck_allocations.csv")
        assert [(r["collector_number"], r["finish"], r["quantity"]) for r in allocations] == [
            ("0", "nonfoil", "2")
        ]

    bob = await with_modules(client, session, "bob", ["binder", "decks"])
    bob_id = 2
    dry = (await upload(client, bob, data, dry_run=True)).json()
    assert dry["errors"] == []
    assert dry["counts"] == {
        "cards.csv": 1,
        "binder_sets.csv": 1,
        "decks.csv": 1,
        "deck_cards.csv": 1,
        "deck_allocations.csv": 1,
    }
    assert await snapshot(session, bob_id) == (0, 0, 0, 0)

    report = (await upload(client, bob, data)).json()
    assert (report["errors"], report["imported"]) == ([], 1)
    assert await snapshot(session, bob_id) == (3, 1, 4, 2)
    # `set` mode on the same bundle leaves everything as it is; `add` adds up.
    assert (await upload(client, bob, data, mode="set")).json()["errors"] == []
    assert await snapshot(session, bob_id) == (3, 1, 4, 2)
    again = (await upload(client, bob, data)).json()
    assert again["errors"] == []
    assert await snapshot(session, bob_id) == (6, 1, 8, 4)
    # The cards-only export is the plain CSV, unchanged.
    cards = await client.get("/api/collection/export", headers=bob)
    assert cards.headers["content-type"].startswith("text/csv")
    assert cards.text == (await client.get("/api/collection/export.csv", headers=bob)).text


async def test_bundle_needs_the_modules(client, session, catalog):  # noqa: F811
    _, data = await alice_bundle(client, session, catalog)
    carol = await with_modules(client, session, "carol", ["binder"])
    refused = await client.get("/api/collection/export", params={"parts": "decks"}, headers=carol)
    assert refused.status_code == 403
    # `all` is what carol can use: no deck files.
    mine = await client.get("/api/collection/export", params={"parts": "all"}, headers=carol)
    with zipfile.ZipFile(io.BytesIO(mine.content)) as archive:
        assert "decks.csv" not in archive.namelist()

    report = (await upload(client, carol, data)).json()
    assert [(e["file"], e["message"]) for e in report["errors"]] == [
        ("decks.csv", "The decks module is not enabled")
    ]
    assert await snapshot(session, 3) == (0, 0, 0, 0)


async def test_bundle_is_all_or_nothing(client, session, catalog):  # noqa: F811
    _, data = await alice_bundle(client, session, catalog)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files = {name: archive.read(name).decode() for name in archive.namelist()}
    bob = await with_modules(client, session, "bob", ["binder", "decks"])

    # More copies allocated than the cards give: nothing is imported, cards neither.
    greedy = dict(files)
    greedy["deck_allocations.csv"] = files["deck_allocations.csv"].replace(",2,tst,", ",4,tst,")
    report = (await upload(client, bob, bundle(greedy))).json()
    assert [(e["file"], e["line"]) for e in report["errors"]] == [("deck_allocations.csv", 2)]
    assert "3 owned copies" in report["errors"][0]["message"]
    assert await snapshot(session, 2) == (0, 0, 0, 0)

    # Rows of every file are checked before anything is written.
    broken = dict(files)
    broken["decks.csv"] = "deck,game,name,format\n1,mtg,Burn,historic\n"
    broken["deck_cards.csv"] = files["deck_cards.csv"].replace("Lightning Bolt,", "Nope,", 1)
    report = (await upload(client, bob, bundle(broken))).json()
    messages = [(e["file"], e["message"]) for e in report["errors"]]
    assert ("decks.csv", "'historic' is not a format of mtg") in messages
    assert await snapshot(session, 2) == (0, 0, 0, 0)


async def test_bundle_zip_checks(client, session, catalog, monkeypatch):  # noqa: F811
    bob = await with_modules(client, session, "bob", ["binder", "decks"])
    cases = {
        b"PK\x03\x04 not a zip": "Not a valid zip file",
        bundle({"cards.csv": "game\n", "../evil.sh": "x"}): "Unknown files in the zip: ../evil.sh",
        bundle({"manifest.json": '{"format": "other"}'}): "manifest.json is not a Zukan export",
        bundle({"manifest.json": '{"format": "zukan-export", "version": 99}', "cards.csv": ""}): (
            "This export comes from a newer Zukan: update this server first"
        ),
        bundle({"manifest.json": '{"format": "zukan-export", "version": 1}'}): (
            "The zip holds no file to import"
        ),
    }
    for data, message in cases.items():
        response = await upload(client, bob, data)
        assert (response.status_code, response.json()["detail"]) == (400, message)
    # Sizes are the bytes read, whatever the zip claims.
    monkeypatch.setattr(export_bundle, "MAX_FILE_BYTES", 10)
    large = await upload(client, bob, bundle({"cards.csv": "x" * 11}))
    assert large.json()["detail"] == "Files in the zip are too large"
