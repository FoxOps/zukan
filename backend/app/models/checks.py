from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CatalogDiscrepancy(Base):
    """A field a secondary catalog source disagrees on with the primary one (whose value is
    kept). Rows the source no longer reports are deleted after its next run.

    An administrator may arbitrate (`resolution`): `primary` keeps the primary's value,
    `secondary` / `custom` write the secondary's / `resolved_value` over it after every
    catalog sync, so the next sync does not undo the choice."""

    __tablename__ = "catalog_discrepancy"
    __table_args__ = (
        Index(
            "uq_catalog_discrepancy",
            "source",
            "set_id",
            "printing_id",
            "field",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("game.id"), index=True)
    source: Mapped[str] = mapped_column(String(32))
    set_id: Mapped[int] = mapped_column(ForeignKey("card_set.id", ondelete="CASCADE"))
    # None: a set field.
    printing_id: Mapped[int | None] = mapped_column(
        ForeignKey("printing.id", ondelete="CASCADE"), index=True
    )
    field: Mapped[str] = mapped_column(String(32))
    primary_value: Mapped[str | None] = mapped_column(String(500))
    secondary_value: Mapped[str | None] = mapped_column(String(500))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # None: open. "primary", "secondary" or "custom".
    resolution: Mapped[str | None] = mapped_column(String(16))
    resolved_value: Mapped[str | None] = mapped_column(String(500))
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Resolved by a field rule (reopened when the rule is removed).
    by_rule: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)


class CatalogFieldRule(Base):
    """Standing arbitration: for this game, source and field, always prefer one side."""

    __tablename__ = "catalog_field_rule"
    __table_args__ = (UniqueConstraint("game_id", "source", "field"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(ForeignKey("game.id"))
    source: Mapped[str] = mapped_column(String(32))
    field: Mapped[str] = mapped_column(String(32))
    # "primary" or "secondary".
    prefer: Mapped[str] = mapped_column(String(16))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
