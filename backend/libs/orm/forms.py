from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Forms(Base):
    __tablename__ = "forms"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    full_name: Mapped[str] = mapped_column(String(200))
    birth_date: Mapped[date] = mapped_column(Date)
    document_type: Mapped[str] = mapped_column(String(20))
    document_number: Mapped[str] = mapped_column(String(30))
    phone: Mapped[str] = mapped_column(String(30))
    address: Mapped[str] = mapped_column(String(300))
    city: Mapped[str] = mapped_column(String(120))
    occupation: Mapped[str] = mapped_column(String(120))
    economic_activity: Mapped[str] = mapped_column(String(120))
    monthly_income: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    monthly_expenses: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    total_assets: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    total_liabilities: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    source_of_funds: Mapped[str] = mapped_column(String(200))
    is_peps: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    def public_dict(self) -> dict:
        return {
            "full_name": self.full_name,
            "birth_date": self.birth_date.isoformat(),
            "document_type": self.document_type,
            "document_number": self.document_number,
            "phone": self.phone,
            "address": self.address,
            "city": self.city,
            "occupation": self.occupation,
            "economic_activity": self.economic_activity,
            "monthly_income": float(self.monthly_income),
            "monthly_expenses": float(self.monthly_expenses),
            "total_assets": float(self.total_assets),
            "total_liabilities": float(self.total_liabilities),
            "source_of_funds": self.source_of_funds,
            "is_peps": self.is_peps,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def get_by_user(cls, user_id: UUID):
        return db_session.session.get(cls, user_id)

    @classmethod
    def upsert(cls, user_id: UUID, **fields):
        existing = cls.get_by_user(user_id)
        if existing is None:
            row = cls(user_id=user_id, **fields)
            db_session.session.add(row)
            db_session.session.flush()
            return row
        for k, v in fields.items():
            setattr(existing, k, v)
        db_session.session.flush()
        return existing
