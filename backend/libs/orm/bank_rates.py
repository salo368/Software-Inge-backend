from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, and_, select
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BankRates(Base):
    __tablename__ = "bank_rates"

    # Composite PK doubles as the lookup index ("highest min_amount <= amount
    # for a given bank+term"), so no extra secondary index is needed.
    bank_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("banks.id", ondelete="CASCADE"), primary_key=True
    )
    term_days: Mapped[int] = mapped_column(Integer, primary_key=True)
    min_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    @classmethod
    def find_applicable(cls, bank_id: int, term_days: int, amount: Decimal):
        """Rate for (bank, term, amount): highest min_amount <= amount.
        Returns None if no bracket applies (amount below the bank's floor)."""
        stmt = (
            select(cls)
            .where(cls.bank_id == bank_id, cls.term_days == term_days, cls.min_amount <= amount)
            .order_by(cls.min_amount.desc())
            .limit(1)
        )
        return db_session.session.execute(stmt).scalars().first()

    @classmethod
    def best_per_bank(cls, term_days: int, amount: Decimal) -> dict[int, Decimal]:
        """{bank_id: rate} for a given (term, amount). Uses DISTINCT ON to pick
        the highest applicable min_amount per bank in a single query. Banks
        whose floor is above `amount` are omitted from the result."""
        subq = (
            select(cls.bank_id, cls.rate, cls.min_amount)
            .where(and_(cls.term_days == term_days, cls.min_amount <= amount))
            .order_by(cls.bank_id, cls.min_amount.desc())
            .distinct(cls.bank_id)
        )
        result = db_session.session.execute(subq).all()
        return {row.bank_id: row.rate for row in result}
