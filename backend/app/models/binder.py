from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.catalog import CardSet


class BinderSet(TimestampMixin, Base):
    """A set a user follows in the Binder module (`app.modules`). Its progress comes
    from the collection: a printing of the set is owned with at least one copy matching
    the optional language and finish."""

    __tablename__ = "binder_set"
    __table_args__ = (UniqueConstraint("user_id", "set_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    # Followed sets are never deleted with the catalog (reset, empty set pruning): the
    # catalog sync fills them again.
    set_id: Mapped[int] = mapped_column(ForeignKey("card_set.id", ondelete="RESTRICT"))
    # Only copies in this language / finish count; None: any.
    language: Mapped[str | None] = mapped_column(String(8))
    finish: Mapped[str | None] = mapped_column(String(32))

    set: Mapped[CardSet] = relationship()
