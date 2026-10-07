from sqlalchemy import ARRAY, Boolean, DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base

TABLE_NAME = "banks"

class Banks(Base):

    __tablename__ = TABLE_NAME

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String())
    name: Mapped[str] = mapped_column(String())
    logo_key: Mapped[str] = mapped_column(String())
    description: Mapped[str] = mapped_column(String())
    tier: Mapped[str] = mapped_column(String())
    rating_by: Mapped[str] = mapped_column(String())
    highlights: Mapped[list[str]] = mapped_column(ARRAY(Text))
    is_active: Mapped[bool] = mapped_column(Boolean)
    created_at = mapped_column(DateTime())
    updated_at = mapped_column(DateTime())

    def get_all(active=None):

        statement = select(Banks).order_by(Banks.tier, Banks.name)

        if active is not None:
            statement = statement.where(Banks.is_active == active)

        return db_session.query(statement=statement, many=True)

    def get_by_id(bank_id):

        statement = (
            select(Banks)
            .where(Banks.id == bank_id)
            .limit(1)
        )

        return db_session.query(statement=statement)
