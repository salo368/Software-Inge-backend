from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, or_, select
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base

TABLE_NAME = "term_band"

class TermBand(Base):

    __tablename__ = TABLE_NAME

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank_id: Mapped[int] = mapped_column(Integer)
    valid_from = mapped_column(DateTime())
    valid_to = mapped_column(DateTime())
    min_days: Mapped[int] = mapped_column(Integer)
    max_days: Mapped[int] = mapped_column(Integer)

    def get_by_bank_term(bank_id, term):
        """The one band (if any) covering `term` for this specific bank."""

        now = datetime.now(timezone.utc)

        statement = (
            select(TermBand)
            .where(
                TermBand.bank_id == bank_id,
                TermBand.min_days <= term,
                TermBand.max_days >= term,
                TermBand.valid_from <= now,
                or_(TermBand.valid_to.is_(None), TermBand.valid_to >= now),
            )
            .limit(1)
        )

        return db_session.query(statement=statement)

    def get_all_by_term(term):
        """Every bank's band (at most one per bank) covering `term`."""

        now = datetime.now(timezone.utc)

        statement = select(TermBand).where(
            TermBand.min_days <= term,
            TermBand.max_days >= term,
            TermBand.valid_from <= now,
            or_(TermBand.valid_to.is_(None), TermBand.valid_to >= now),
        )

        return db_session.query(statement=statement, many=True)
