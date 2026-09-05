from datetime import datetime
from decimal import Decimal
from typing import Self

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from utils.orm.model import Model


class DigitalSignatures(Model):
    __tablename__ = "digital_signatures"

    cdt_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cdts.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    pdf_key: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    pos_x: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    pos_y: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    cedula_front_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    cedula_back_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    face_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    signed_pdf_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    otp_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    otp_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    @classmethod
    def get_by_token(cls, token: str) -> Self | None:
        return cls._get_one(token=token)
