from decimal import Decimal

from sqlalchemy import Integer, Numeric, select, tuple_
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base
from libs.orm.rates_term_band import TermBand

TABLE_NAME = "rate"

class Rate(Base):

    __tablename__ = TABLE_NAME

    term_band_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    amount_band_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))

    def get_by_bands(amount_band_id, term_band_id):
        """The rate for one specific (amount_band, term_band) pair, or None."""

        statement = (
            select(Rate)
            .where(
                Rate.amount_band_id == amount_band_id,
                Rate.term_band_id == term_band_id,
            )
            .limit(1)
        )

        return db_session.query(statement=statement)

    def get_all_by_bands(band_pairs):
        """[(bank_id, rate), ...] best rate first, for a list of
        (amount_band_id, term_band_id) pairs, one per bank."""

        if not band_pairs:
            return []

        statement = (
            select(TermBand.bank_id, Rate.rate)
            .join(TermBand, TermBand.id == Rate.term_band_id)
            .where(tuple_(Rate.amount_band_id, Rate.term_band_id).in_(band_pairs))
            .order_by(Rate.rate.desc())
        )

        rows = db_session.session.execute(statement).all()
        return [(row.bank_id, row.rate) for row in rows]
