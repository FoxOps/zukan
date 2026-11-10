"""Optional modules (settings, server-wide switch) and the Binder module."""

import asyncio

import pytest
from sqlalchemy import func, select

from app.models import CardSet, Printing, Role
from app.services import jobs
from tests.conftest import bearer, make_user, sync_sorcery


@pytest.fixture
async def catalog(session, sorcery_api):
    from app.main import register_games

    await register_games()
    await sync_sorcery(session)


@pytest.fixture
async def alice(client, session, catalog):
    await make_user(session)
    headers = await bearer(client, "alice")
    response = await client.patch("/api/auth/me", json={"modules": ["binder"]}, headers=headers)
    assert response.status_code == 200, response.text
    return headers


async def set_id(session, code: str) -> int:
    return await session.scalar(select(CardSet.id).where(CardSet.code == code))


async def printings(session, code: str) -> list[Printing]:
    return list(
        await session.scalars(
            select(Printing).join(CardSet).where(CardSet.code == code).order_by(Printing.id)
        )
    )


async def adjust(client, headers, printing: Printing, delta: int, **extra):
    body = {
        "printing_id": printing.id,
        "finish": printing.finishes[0],
        "language": "en",
        "delta": delta,
        **extra,
    }
    response = await client.post("/api/collection/adjust", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_modules_setting_and_server_switch(client, session, catalog):
    await make_user(session)
    await make_user(session, "root", role=Role.admin)
    alice = await bearer(client, "alice")
    root = await bearer(client, "root")

    me = (await client.get("/api/auth/me", headers=alice)).json()
    assert (me["modules"], me["available_modules"]) == ([], ["binder"])
    # Plain Zukan: the module's routes are refused.
    assert (await client.get("/api/binder", headers=alice)).status_code == 403
    unknown = await client.patch("/api/auth/me", json={"modules": ["chess"]}, headers=alice)
    assert unknown.status_code == 422
    on = await client.patch("/api/auth/me", json={"modules": ["binder", "binder"]}, headers=alice)
    assert on.json()["modules"] == ["binder"]
    assert (await client.get("/api/binder", headers=alice)).status_code == 200

    # Turned off server-wide: hidden and refused, the user's choice kept.
    assert (
        await client.put("/api/admin/modules", json={"disabled": []}, headers=alice)
    ).status_code == 403
    assert (
        await client.put("/api/admin/modules", json={"disabled": ["chess"]}, headers=root)
    ).status_code == 422
    off = await client.put("/api/admin/modules", json={"disabled": ["binder"]}, headers=root)
    assert off.json() == {"modules": ["binder"], "disabled": ["binder"]}
    me = (await client.get("/api/auth/me", headers=alice)).json()
    assert (me["modules"], me["available_modules"]) == ([], [])
    assert (await client.get("/api/binder", headers=alice)).status_code == 403
    await client.put("/api/admin/modules", json={"disabled": []}, headers=root)
    assert (await client.get("/api/auth/me", headers=alice)).json()["modules"] == ["binder"]
    assert (await client.get("/api/admin/modules", headers=root)).json()["disabled"] == []


async def test_follow_sets(client, session, alice):
    alpha = await set_id(session, "001")
    follow = await client.post("/api/binder", json={"set_id": alpha}, headers=alice)
    assert follow.status_code == 201, follow.text
    binder = follow.json()
    total = await session.scalar(
        select(func.count()).select_from(Printing).where(Printing.set_id == alpha)
    )
    assert (binder["game_id"], binder["owned"], binder["total"]) == ("sorcery", 0, total)
    assert binder["set"]["id"] == alpha
    again = await client.post("/api/binder", json={"set_id": alpha}, headers=alice)
    assert again.status_code == 409
    assert (
        await client.post("/api/binder", json={"set_id": 999999}, headers=alice)
    ).status_code == 404
    for bad in ({"language": "xx"}, {"finish": "rainbow"}):
        response = await client.patch(f"/api/binder/{binder['id']}", json=bad, headers=alice)
        assert response.status_code == 422, bad

    # Only its owner sees a binder.
    await make_user(session, "bob")
    bob = await bearer(client, "bob")
    await client.patch("/api/auth/me", json={"modules": ["binder"]}, headers=bob)
    assert (await client.get(f"/api/binder/{binder['id']}", headers=bob)).status_code == 404
    assert (await client.delete(f"/api/binder/{binder['id']}", headers=bob)).status_code == 404
    assert (await client.get("/api/binder", headers=bob)).json() == []

    assert [b["id"] for b in (await client.get("/api/binder", headers=alice)).json()] == [
        binder["id"]
    ]
    gone = await client.delete(f"/api/binder/{binder['id']}", headers=alice)
    assert gone.status_code == 204
    assert (await client.get("/api/binder", headers=alice)).json() == []


async def test_progress_from_collection(client, session, alice):
    alpha = await set_id(session, "001")
    first, second, *_ = await printings(session, "001")
    binder = (await client.post("/api/binder", json={"set_id": alpha}, headers=alice)).json()

    # Copies added anywhere count, one per printing whatever the number of copies.
    await adjust(client, alice, first, 2)
    await adjust(client, alice, first, 1, condition="EX")
    detail = (await client.get(f"/api/binder/{binder['id']}", headers=alice)).json()
    assert detail["binder"]["owned"] == 1
    rows = {row["printing_id"]: row for row in detail["rows"]}
    assert len(rows) == binder["total"]
    assert rows[first.id]["quantity"] == 3
    assert [(i["condition"], i["quantity"]) for i in rows[first.id]["items"]] == [
        ("NM", 2),
        ("EX", 1),
    ]
    assert (rows[second.id]["quantity"], rows[second.id]["items"]) == (0, [])
    assert rows[first.id]["name"]

    # Removed copies no longer count.
    await adjust(client, alice, first, -2)
    await adjust(client, alice, first, -1, condition="EX")
    listed = (await client.get("/api/binder", headers=alice)).json()
    assert listed[0]["owned"] == 0

    # A language filter only counts copies in that language.
    await adjust(client, alice, second, 1)
    response = await client.patch(
        f"/api/binder/{binder['id']}", json={"language": "en"}, headers=alice
    )
    assert response.status_code == 200, response.text
    assert response.json()["owned"] == 1
    finish = second.finishes[-1]
    response = await client.patch(
        f"/api/binder/{binder['id']}", json={"finish": finish}, headers=alice
    )
    assert response.json()["finish"] == finish
    other_finishes = [f for f in second.finishes if f != finish]
    if other_finishes:
        assert response.json()["owned"] == 0
    cleared = await client.patch(
        f"/api/binder/{binder['id']}", json={"language": None, "finish": None}, headers=alice
    )
    assert (cleared.json()["language"], cleared.json()["finish"], cleared.json()["owned"]) == (
        None,
        None,
        1,
    )


async def test_catalog_reset_keeps_followed_sets(client, session, alice):
    """A reset deletes sets nobody owns a card of; followed ones stay (no binder lost),
    empty until the catalog sync fills them again under the same id."""
    await make_user(session, "root", role=Role.admin)
    root = await bearer(client, "root")
    followed_id = await session.scalar(select(CardSet.id).order_by(CardSet.id).limit(1))
    total = await session.scalar(
        select(func.count()).select_from(Printing).where(Printing.set_id == followed_id)
    )
    binder = (await client.post("/api/binder", json={"set_id": followed_id}, headers=alice)).json()

    response = await client.post("/api/admin/games/sorcery/reset", headers=root)
    assert response.status_code == 200, response.text
    session.expire_all()
    assert await session.get(CardSet, followed_id) is not None
    assert (await client.get(f"/api/binder/{binder['id']}", headers=alice)).json()["rows"] == []

    await asyncio.gather(*await jobs.run_queued())
    listed = (await client.get("/api/binder", headers=alice)).json()
    assert [(b["id"], b["set"]["id"], b["total"]) for b in listed] == [
        (binder["id"], followed_id, total)
    ]
