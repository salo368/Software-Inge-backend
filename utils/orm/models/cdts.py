from datetime import datetime
from decimal import Decimal
from typing import Self

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from utils.orm.model import Model


class Cdts(Model):
    __tablename__ = "cdts"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    term: Mapped[int] = mapped_column(Integer, nullable=False)
    signature_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @classmethod
    def get_by_user_id(cls, user_id: int) -> list[Self]:
        return cls._get_many(user_id=user_id)
