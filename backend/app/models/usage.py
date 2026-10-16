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
