from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CatalogDiscrepancy(Base):
    """A field a secondary catalog source disagrees on with the primary one (whose value is
    kept). Rows the source no longer reports are deleted after its next run."""

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
