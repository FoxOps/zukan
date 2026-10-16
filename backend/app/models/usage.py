from datetime import date

from sqlalchemy import Date, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ApiUsage(Base):
    """Requests made to an external API with a quota, per period (day or month, by
    source), so a limited free tier is not used up by one deployment."""

    __tablename__ = "api_usage"
    __table_args__ = (UniqueConstraint("source", "period_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    # First day of the day / month counted.
    period_start: Mapped[date] = mapped_column(Date)
    requests: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class GapCheck(Base):
    """A set a gap source with a quota looked at, and how many printings still had gaps
    after it. The source skips the set while that number is the same (it had nothing for
    them), for a while."""

    __tablename__ = "gap_check"
    __table_args__ = (UniqueConstraint("source", "game_id", "set_external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    game_id: Mapped[str] = mapped_column(String(32))
    set_external_id: Mapped[str] = mapped_column(String(128))
    gaps: Mapped[int] = mapped_column(Integer)
    checked_on: Mapped[date] = mapped_column(Date)
