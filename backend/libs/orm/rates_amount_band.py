from decimal import Decimal

from sqlalchemy import Integer, Numeric, select
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base

TABLE_NAME = "rates_amount_band"

class AmountBand(Base):

    __tablename__ = TABLE_NAME

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank_id: Mapped[int] = mapped_column(Integer)
    min_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    max_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))

    def get_by_bank_amount(bank_id, amount):
        """The one band (if any) covering `amount` for this specific bank."""

        statement = (
            select(AmountBand)
            .where(
                AmountBand.bank_id == bank_id,
                AmountBand.min_amount <= amount,
                AmountBand.max_amount >= amount,
            )
            .limit(1)
        )

        return db_session.query(statement=statement)

    def get_all_by_amount(amount):
        """Every bank's band (at most one per bank) covering `amount`."""

        statement = select(AmountBand).where(
            AmountBand.min_amount <= amount,
            AmountBand.max_amount >= amount,
        )

        return db_session.query(statement=statement, many=True)
