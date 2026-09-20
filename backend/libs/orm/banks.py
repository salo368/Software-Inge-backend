from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import ARRAY, Boolean, DateTime, Integer, Numeric, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Banks(Base):
    __tablename__ = "banks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    logo_key: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    tier: Mapped[str] = mapped_column(String(10))
    rating_by: Mapped[str] = mapped_column(String(80))
    min_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    highlights: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    def public_dict(self, assets_base_url: str = "") -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "logo_url": f"{assets_base_url.rstrip('/')}/{self.logo_key}" if assets_base_url else self.logo_key,
            "description": self.description,
            "tier": self.tier,
            "rating_by": self.rating_by,
            "min_amount": float(self.min_amount),
            "highlights": list(self.highlights or []),
        }

    @classmethod
    def list_active(cls):
        stmt = select(cls).where(cls.is_active.is_(True)).order_by(cls.tier, cls.name)
        return list(db_session.session.execute(stmt).scalars().all())

    @classmethod
    def get_by_id(cls, bank_id: int):
        return db_session.session.get(cls, bank_id)
