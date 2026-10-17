import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import CardSet, PriceSnapshot, Printing
from tests.conftest import bearer, make_user, sync_sorcery


@pytest.fixture
async def catalog(session, sorcery_api):
    from app.main import register_games

    await register_games()
    await sync_sorcery(session)


@pytest.fixture
async def alice(client, session, catalog):
    await make_user(session)
    return await bearer(client, "alice")


async def printing_id(session, set_code: str, external_id: str) -> int:
    return await session.scalar(
        select(Printing.id)
        .join(CardSet)
        .where(CardSet.code == set_code, Printing.external_id == external_id)
    )


async def adjust(client, headers, printing, delta, finish="standard", **extra):
    body = {"printing_id": printing, "finish": finish, "language": "en", "delta": delta, **extra}
    return await client.post("/api/collection/adjust", json=body, headers=headers)


@pytest.mark.smoke
async def test_adjust_add_remove_and_validation(client, session, alice):
    abundance = await printing_id(session, "001", "abundance-b")
    response = await adjust(client, alice, abundance, 3)
    assert response.status_code == 200, response.text
    item = response.json()["item"]
    assert (item["name"], item["quantity"], item["condition"]) == ("Abundance", 3, "NM")

    removed = await adjust(client, alice, abundance, -1)
    assert removed.status_code == 200, removed.text
    assert removed.json()["item"]["quantity"] == 2
    too_many = await adjust(client, alice, abundance, -5)
    assert too_many.status_code == 409
    assert "Not enough copies" in too_many.json()["detail"]

    # A different condition is a different item; removing from nothing fails.
    assert (await adjust(client, alice, abundance, -1, condition="EX")).status_code == 409
    assert (await adjust(client, alice, abundance, 1, finish="rainbow")).status_code == 409
    assert (await adjust(client, alice, abundance, 1, language="xx")).status_code == 409
    assert (await adjust(client, alice, abundance, 0)).status_code == 409
    assert (await adjust(client, alice, 999999, 1)).status_code == 404

    items = (await client.get("/api/collection", headers=alice)).json()
    assert [(i["quantity"], i["finish"]) for i in items["items"]] == [(2, "standard")]

    # Collections are private.
    await make_user(session, "bob")
    bob = await bearer(client, "bob")
    assert (await client.get("/api/collection", headers=bob)).json()["total"] == 0
    item_id = items["items"][0]["id"]
    assert (await client.get(f"/api/collection/items/{item_id}", headers=bob)).status_code == 404


async def test_concurrent_adjustments_are_not_lost(client, session, alice):
    abundance = await printing_id(session, "001", "abundance-b")
    responses = await asyncio.gather(*(adjust(client, alice, abundance, 1) for _ in range(10)))
    assert all(r.status_code == 200 for r in responses)
    items = (await client.get("/api/collection", headers=alice)).json()["items"]
    assert items[0]["quantity"] == 10


@pytest.mark.smoke
async def test_undo(client, session, alice):
    abundance = await printing_id(session, "001", "abundance-b")
    added = (await adjust(client, alice, abundance, 2, source="scan")).json()
    removed = (await adjust(client, alice, abundance, -1)).json()

    undo = await client.post(
        f"/api/collection/transactions/{removed['transaction_id']}/undo", headers=alice
    )
    assert undo.json()["quantity"] == 2
    again = await client.post(
        f"/api/collection/transactions/{removed['transaction_id']}/undo", headers=alice
    )
    assert again.status_code == 409

    await adjust(client, alice, abundance, -2)
    blocked = await client.post(
        f"/api/collection/transactions/{added['transaction_id']}/undo", headers=alice
    )
    assert blocked.status_code == 409
    history = (await client.get("/api/collection/transactions", headers=alice)).json()
    assert [(t["delta"], t["undone"], t["source"]) for t in history] == [
        (-2, False, "web"),
        (-1, True, "web"),
        (2, False, "scan"),
    ]
    assert history[0]["name"] == "Abundance"

    await make_user(session, "bob")
    bob = await bearer(client, "bob")
    stolen = await client.post(
        f"/api/collection/transactions/{added['transaction_id']}/undo", headers=bob
    )
    assert stolen.status_code == 404


async def add_price(session, printing, finish, day, trend):
    session.add(
        PriceSnapshot(
            printing_id=printing, finish=finish, date=day, source="cardmarket", trend=trend
        )
    )
    await session.commit()


async def test_prices_value_and_history(client, session, alice):
    abundance = await printing_id(session, "001", "abundance-b")
    aqueduct = (
        await session.execute(select(Printing.id, Printing.finishes).join(CardSet).limit(1))
    ).first()
    today = date.today()
    await add_price(session, abundance, "standard", today - timedelta(days=1), Decimal("1.00"))
    await add_price(session, abundance, "standard", today, Decimal("2.50"))
    await add_price(session, abundance, "foil", today, Decimal("10.00"))

    await adjust(client, alice, abundance, 3)
    item = (await adjust(client, alice, abundance, 1, finish="foil")).json()["item"]
    assert (item["market_price"], item["unit_price"], item["total"]) == ("10.00", "10.00", "10.00")

    other = (await adjust(client, alice, aqueduct.id, 2, finish=aqueduct.finishes[0])).json()
    assert other["item"]["unit_price"] is None
    priced = await client.patch(
        f"/api/collection/items/{other['item']['id']}",
        json={"manual_price": "4.20", "notes": "signed"},
        headers=alice,
    )
    assert priced.json()["unit_price"] == "4.20" and priced.json()["notes"] == "signed"

    value = (await client.get("/api/collection/value", headers=alice)).json()
    # 3 x 2.50 + 1 x 10 + 2 x 4.20
    assert value["total"] == "25.90"
    assert value["games"] == [
        {
            "game_id": "sorcery",
            "currency": "EUR",
            "total": "25.90",
            "quantity": 6,
            "priced": 6,
            "unpriced": 0,
        }
    ]

    history = (
        await client.get("/api/collection/value/history", params={"days": 3}, headers=alice)
    ).json()
    # Day -2: manual price only; day -1: abundance standard known (1.00); today: all prices.
    assert history["currency"] == "EUR"
    assert [p["value"] for p in history["points"]] == ["8.40", "11.40", "25.90"]

    # TCGplayer preferred: Sorcery has no TCGplayer prices and stays on Cardmarket, in
    # euros, never added to dollar totals.
    me = await client.patch("/api/auth/me", json={"price_source": "tcgplayer"}, headers=alice)
    # The main source changes, the others stay shown.
    assert me.json()["price_source"] == "tcgplayer"
    assert me.json()["price_sources"] == ["tcgplayer", "cardmarket"]
    value = (await client.get("/api/collection/value", headers=alice)).json()
    assert (value["currency"], value["total"]) == ("USD", "0")
    assert value["totals"] == [{"currency": "EUR", "total": "25.90"}]
    history = (
        await client.get("/api/collection/value/history", params={"days": 1}, headers=alice)
    ).json()
    assert history == {"currency": "USD", "points": [{"date": str(date.today()), "value": "0"}]}
    bad = await client.patch("/api/auth/me", json={"price_source": "nope"}, headers=alice)
    assert bad.status_code == 422
    await client.patch("/api/auth/me", json={"price_source": "cardmarket"}, headers=alice)

    reset = await client.patch(
        f"/api/collection/items/{other['item']['id']}", json={"manual_price": None}, headers=alice
    )
    assert reset.json()["unit_price"] is None

    card = (await client.get(f"/api/cards/{item['card_id']}", headers=alice)).json()
    alpha = next(p for p in card["printings"] if p["id"] == abundance)
    assert {(o["finish"], o["quantity"]) for o in alpha["owned"]} == {("standard", 3), ("foil", 1)}
    assert {(p["finish"], p["trend"]) for p in alpha["prices"]} == {
        ("standard", "2.50"),
        ("foil", "10.00"),
    }
    prices = (await client.get(f"/api/printings/{abundance}/prices", headers=alice)).json()
    assert [(p["finish"], p["trend"]) for p in prices] == [
        ("standard", "1.00"),
        ("foil", "10.00"),
        ("standard", "2.50"),
    ]


async def test_set_quantity_and_delete(client, session, alice):
    abundance = await printing_id(session, "001", "abundance-b")
    item = (await adjust(client, alice, abundance, 1)).json()["item"]
    url = f"/api/collection/items/{item['id']}"
    assert (await client.patch(url, json={"quantity": 4}, headers=alice)).json()["quantity"] == 4
    assert (await client.patch(url, json={"quantity": -1}, headers=alice)).status_code == 422
    history = (
        await client.get(
            "/api/collection/transactions", params={"item_id": item["id"]}, headers=alice
        )
    ).json()
    assert [t["delta"] for t in history] == [3, 1]

    # Emptied items are hidden unless asked for.
    await client.patch(url, json={"quantity": 0}, headers=alice)
    assert (await client.get("/api/collection", headers=alice)).json()["total"] == 0
    shown = await client.get("/api/collection", params={"include_empty": True}, headers=alice)
    assert shown.json()["total"] == 1

    assert (await client.delete(url, headers=alice)).status_code == 204
    assert (await client.get(url, headers=alice)).status_code == 404


async def test_list_filters(client, session, alice):
    abundance = await printing_id(session, "001", "abundance-b")
    beta = await printing_id(session, "002", "abundance-b")
    await adjust(client, alice, abundance, 1)
    await adjust(client, alice, beta, 2, finish="foil", condition="EX")
    druid = (await client.get("/api/cards", params={"q": "druid"}, headers=alice)).json()
    detail = (await client.get(f"/api/cards/{druid['items'][0]['id']}", headers=alice)).json()
    printing = detail["printings"][0]
    await adjust(client, alice, printing["id"], 5, finish=printing["finishes"][0])

    async def names(**params):
        page = (await client.get("/api/collection", params=params, headers=alice)).json()
        return [(i["name"], i["set"]["code"]) for i in page["items"]]

    assert await names(q="abund", sort="name") == [("Abundance", "001"), ("Abundance", "002")]
    assert await names(finish="foil") == [("Abundance", "002")]
    assert await names(condition="EX") == [("Abundance", "002")]
    assert await names(color="water", game="sorcery") == [
        ("Abundance", "001"),
        ("Abundance", "002"),
    ]
    assert (await names(sort="quantity"))[0][0] == "Druid"
    assert await names(game="mtg") == []


CSV = """game,set_code,collector_number,name,language,finish,condition,quantity,manual_price,notes
sorcery,001,abundance-b,Abundance,en,standard,NM,2,,
sorcery,002,abundance-b,Abundance,en,foil,EX,1,"1,50",binder 3
"""


async def import_file(client, headers, text: str | bytes, **params):
    data = text if isinstance(text, bytes) else text.encode()
    return await client.post(
        "/api/collection/import",
        params=params,
        files={"file": ("collection.csv", data, "text/csv")},
        headers=headers,
    )


@pytest.mark.smoke
async def test_csv_import_export_round_trip(client, session, alice):
    dry = (await import_file(client, alice, CSV, dry_run=True)).json()
    assert (dry["rows"], dry["imported"], dry["errors"]) == (2, 0, [])
    assert (await client.get("/api/collection", headers=alice)).json()["total"] == 0

    report = (await import_file(client, alice, CSV)).json()
    assert report["imported"] == 2
    exported = (await client.get("/api/collection/export.csv", headers=alice)).text
    assert exported.splitlines() == [
        "game,set_code,collector_number,name,language,finish,condition,quantity,manual_price,notes",
        "sorcery,001,abundance-b,Abundance,en,standard,NM,2,,",
        "sorcery,002,abundance-b,Abundance,en,foil,EX,1,1.50,binder 3",
    ]

    # Adding the same file doubles quantities; `set` mode restores them.
    await import_file(client, alice, CSV)
    await import_file(client, alice, CSV, mode="set")
    items = (await client.get("/api/collection", params={"sort": "set"}, headers=alice)).json()
    assert sorted(i["quantity"] for i in items["items"]) == [1, 2]

    # Another user imports the export as is (semicolons, as spreadsheets often write).
    await make_user(session, "bob")
    bob = await bearer(client, "bob")
    semicolons = exported.replace(",", ";").replace("1.50", "1,50")
    assert (await import_file(client, bob, semicolons)).json()["imported"] == 2
    assert (await client.get("/api/collection/export.csv", headers=bob)).text == exported


async def test_csv_import_rejects_invalid_files(client, session, alice):
    bad = CSV + (
        "sorcery,001,nope,Missing,en,standard,NM,1,,\n"
        "pokemon,001,abundance-b,,en,standard,NM,1,,\n"
        "chess,001,abundance-b,,en,standard,NM,1,,\n"
        "sorcery,001,abundance-b,,en,rainbow,NM,1,,\n"
        "sorcery,001,abundance-b,,en,standard,NM,many,,\n"
    )
    report = (await import_file(client, alice, bad)).json()
    assert report["imported"] == 0
    assert [e["line"] for e in report["errors"]] == [4, 5, 6, 7, 8]
    assert "No printing" in report["errors"][0]["message"]
    assert "chess" in report["errors"][2]["message"]
    assert (await client.get("/api/collection", headers=alice)).json()["total"] == 0

    missing = (await import_file(client, alice, "game,name\nsorcery,x\n")).json()
    assert "Missing columns" in missing["errors"][0]["message"]
    binary = await import_file(client, alice, b"\xff\xfe\x00game")
    assert binary.status_code == 400


async def test_sort_by_price(client, session, alice):
    abundance = await printing_id(session, "001", "abundance-b")
    beta = await printing_id(session, "002", "abundance-b")
    await add_price(session, abundance, "standard", date.today(), Decimal("2.00"))
    await adjust(client, alice, abundance, 1)
    item = (await adjust(client, alice, beta, 1)).json()["item"]
    await client.patch(
        f"/api/collection/items/{item['id']}", json={"manual_price": "5.00"}, headers=alice
    )

    async def codes(sort):
        page = (await client.get("/api/collection", params={"sort": sort}, headers=alice)).json()
        return [i["set"]["code"] for i in page["items"]]

    assert await codes("price_asc") == ["001", "002"]
    assert await codes("price_desc") == ["002", "001"]


async def test_quotes_without_low_keep_stored_low(session, catalog):
    """The catalog's quotes (trend only) must not wipe the price guide's lowest price."""
    from app.games.base import PriceQuote
    from app.services.prices import printing_ids, store_quotes

    abundance = await printing_id(session, "001", "abundance-b")
    set_ext = await session.scalar(
        select(CardSet.external_id).join(Printing).where(Printing.id == abundance)
    )
    ids = await printing_ids(session, "sorcery")
    today = date.today()
    guide = PriceQuote(set_ext, "abundance-b", "standard", Decimal("2"), Decimal("1"), Decimal("3"))
    await store_quotes(session, [guide], today, ids)
    catalog_quote = PriceQuote(set_ext, "abundance-b", "standard", Decimal("2.20"))
    await store_quotes(session, [catalog_quote], today, ids)
    await session.commit()
    row = await session.scalar(
        select(PriceSnapshot).where(
            PriceSnapshot.printing_id == abundance, PriceSnapshot.date == today
        )
    )
    await session.refresh(row)
    assert (row.trend, row.low, row.avg) == (Decimal("2.20"), Decimal("1.00"), Decimal("3.00"))


async def test_price_trends(client, session, alice):
    abundance = await printing_id(session, "001", "abundance-b")
    today = date.today()
    for days, trend in ((30, "2.52"), (1, "1.00"), (0, "2.50")):
        await add_price(
            session, abundance, "standard", today - timedelta(days=days), Decimal(trend)
        )
    await adjust(client, alice, abundance, 3)
    await adjust(client, alice, abundance, 1, finish="foil")
    items = (await client.get("/api/collection", headers=alice)).json()["items"]
    trends = {i["finish"]: i["trends"] for i in items}
    # Yesterday 1.00: up. A week and a month ago the last known price was 2.52: stable.
    assert trends["standard"] == {
        "d1": {"direction": "up", "change": 1.5},
        "d7": {"direction": "flat", "change": -0.0079},
        "d30": {"direction": "flat", "change": -0.0079},
    }
    # No price history.
    assert trends["foil"] == {"d1": None, "d7": None, "d30": None}


async def test_movers(client, session, alice):
    abundance = await printing_id(session, "001", "abundance-b")
    aqueduct = await printing_id(session, "001", "aqueduct-b")
    today = date.today()
    for printing, before, now in ((abundance, "1.00", "2.50"), (aqueduct, "4.00", "3.00")):
        await add_price(session, printing, "standard", today - timedelta(days=1), Decimal(before))
        await add_price(session, printing, "standard", today, Decimal(now))
    await adjust(client, alice, abundance, 3)
    await adjust(client, alice, aqueduct, 2)
    # No price history: never a mover.
    await adjust(client, alice, abundance, 1, finish="foil")
    movers = (
        await client.get("/api/collection/movers", params={"period": "d1"}, headers=alice)
    ).json()
    assert [(m["item"]["name"], m["change"]) for m in movers["risers"]] == [("Abundance", "4.50")]
    assert [(m["item"]["name"], m["change"]) for m in movers["fallers"]] == [("Aqueduct", "-2.00")]
    week = (await client.get("/api/collection/movers", headers=alice)).json()
    assert week["period"] == "d7" and week["risers"] == []
