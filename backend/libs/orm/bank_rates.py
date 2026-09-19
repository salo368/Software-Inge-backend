from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BankRates(Base):
    __tablename__ = "bank_rates"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    bank_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("banks.id", ondelete="CASCADE")
    )
    term_days: Mapped[int] = mapped_column(Integer)
    min_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    @classmethod
    def find_applicable(cls, bank_id: UUID, term_days: int, amount: Decimal):
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
    def best_per_bank(cls, term_days: int, amount: Decimal) -> dict[UUID, Decimal]:
        """Returns {bank_id: rate} para el (term, amount) dado, un rate por banco.
        Un banco sin bracket aplicable (amount < todos sus min_amount) queda fuera."""
        # DISTINCT ON in Postgres: para cada bank_id, la fila con el mayor
        # min_amount <= amount. La ORM lo expresa mas directo con dos queries
        # pero DISTINCT ON evita el N+1.
        from sqlalchemy import and_

        subq = (
            select(cls.bank_id, cls.rate, cls.min_amount)
            .where(
                and_(
                    cls.term_days == term_days,
                    cls.min_amount <= amount,
                )
            )
            .order_by(cls.bank_id, cls.min_amount.desc())
            .distinct(cls.bank_id)
        )
        result = db_session.session.execute(subq).all()
        return {row.bank_id: row.rate for row in result}
