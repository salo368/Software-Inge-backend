from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, select
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base

STAGES = ("form", "documents", "signature", "payment", "done")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Processes(Base):
    __tablename__ = "processes"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    bank_id: Mapped[int] = mapped_column(Integer, ForeignKey("banks.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    term_days: Mapped[int] = mapped_column(Integer)
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    stage: Mapped[str] = mapped_column(String(20), default="form")
    form_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # Points to the signature ceremony that belongs to this process, if
    # any. Set by `processes.create_signature_ceremony` after calling
    # `POST /signatures`. Null while the process is still in `form` or
    # `documents`. NOT a FK: signatures is a generic service and does not
    # know about processes.
    sign_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    def public_dict(self) -> dict:
        return {
            "id": str(self.id),
            "bank_id": self.bank_id,
            "amount": float(self.amount),
            "term_days": self.term_days,
            "rate": float(self.rate),
            "stage": self.stage,
            "form_snapshot": self.form_snapshot,
            "sign_id": self.sign_id,
            "signed_at": self.signed_at.isoformat() if self.signed_at else None,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def get_by_id(cls, process_id: UUID):
        return db_session.session.get(cls, process_id)

    @classmethod
    def list_by_user(cls, user_id: UUID):
        stmt = select(cls).where(cls.user_id == user_id).order_by(cls.created_at.desc())
        return list(db_session.session.execute(stmt).scalars().all())

    @classmethod
    def create(cls, *, user_id: UUID, bank_id: int, amount: Decimal, term_days: int, rate: Decimal):
        row = cls(user_id=user_id, bank_id=bank_id, amount=amount, term_days=term_days, rate=rate)
        db_session.session.add(row)
        db_session.session.flush()
        return row

    def advance_to(self, next_stage: str) -> None:
        if next_stage not in STAGES:
            raise ValueError(f"invalid stage {next_stage!r}")
        self.stage = next_stage
        now = _utcnow()
        if next_stage == "payment":
            self.signed_at = now
        elif next_stage == "done":
            self.paid_at = now
            self.completed_at = now
        db_session.session.flush()
