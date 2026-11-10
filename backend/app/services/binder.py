"""Binder module: progress of followed sets, read from the collection."""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BinderSet, CollectionItem, Printing


def _same(column: ColumnElement[str], wanted: ColumnElement[str] | str | None) -> Any:
    if wanted is None:
        return true()
    if isinstance(wanted, str):
        return column == wanted
    return or_(wanted.is_(None), column == wanted)


def counts(
    language: ColumnElement[str] | str | None, finish: ColumnElement[str] | str | None
) -> ColumnElement[bool]:
    """Collection items counting for a binder: copies left, in the binder's language and
    finish (values of one binder, or `BinderSet` columns in a join)."""
    return and_(
        CollectionItem.quantity > 0,
        _same(CollectionItem.language, language),
        _same(CollectionItem.finish, finish),
    )


async def progress(
    session: AsyncSession, user_id: int, binders: Iterable[BinderSet]
) -> dict[int, tuple[int, int]]:
    """(owned printings, printings) of each binder."""
    binders = list(binders)
    if not binders:
        return {}
    set_ids = {b.set_id for b in binders}
    totals = dict(
        (
            await session.execute(
                select(Printing.set_id, func.count())
                .where(Printing.set_id.in_(set_ids))
                .group_by(Printing.set_id)
            )
        ).all()
    )
    owned = dict(
        (
            await session.execute(
                select(BinderSet.id, func.count(func.distinct(Printing.id)))
                .join(Printing, Printing.set_id == BinderSet.set_id)
                .join(
                    CollectionItem,
                    and_(
                        CollectionItem.printing_id == Printing.id,
                        CollectionItem.user_id == user_id,
                        counts(BinderSet.language, BinderSet.finish),
                    ),
                )
                .where(BinderSet.id.in_([b.id for b in binders]))
                .group_by(BinderSet.id)
            )
        ).all()
    )
    return {b.id: (owned.get(b.id, 0), totals.get(b.set_id, 0)) for b in binders}
