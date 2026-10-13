import datetime as dt
import enum
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.catalog import Printing


class Condition(enum.StrEnum):
    """Cardmarket grading scale."""

    MT = "MT"  # Mint
    NM = "NM"  # Near Mint
    EX = "EX"  # Excellent
    GD = "GD"  # Good
    LP = "LP"  # Light Played
    PL = "PL"  # Played
    PO = "PO"  # Poor


class PriceSnapshot(Base):
    __tablename__ = "price_snapshot"
    __table_args__ = (UniqueConstraint("printing_id", "finish", "date", "source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    printing_id: Mapped[int] = mapped_column(
        ForeignKey("printing.id", ondelete="CASCADE"), index=True
    )
    finish: Mapped[str] = mapped_column(String(32))
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    trend: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    low: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    avg: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))


class CollectionItem(TimestampMixin, Base):
    __tablename__ = "collection_item"
    __table_args__ = (
        UniqueConstraint("user_id", "printing_id", "finish", "condition", "language"),
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    printing_id: Mapped[int] = mapped_column(ForeignKey("printing.id"), index=True)
    finish: Mapped[str] = mapped_column(String(32))
    condition: Mapped[str] = mapped_column(String(2), default=Condition.NM)
    language: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[int] = mapped_column(default=0)
    # Overrides API prices (only source of price for games without price data).
    manual_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    notes: Mapped[str | None] = mapped_column(String(1000))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    printing: Mapped[Printing] = relationship()


class StockTransaction(TimestampMixin, Base):
    __tablename__ = "stock_transaction"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("collection_item.id", ondelete="CASCADE"), index=True
    )
    delta: Mapped[int]
    source: Mapped[str] = mapped_column(String(16))  # web | scan | import
    undone: Mapped[bool] = mapped_column(default=False)
