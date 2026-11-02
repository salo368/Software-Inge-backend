from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, insert, select, update
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base

TABLE_NAME = "processes"


class ProcessStage(str, Enum):
    FORM = "FORM"
    DOCUMENTS = "DOCUMENTS"
    SIGNATURE = "SIGNATURE"
    PAYMENT = "PAYMENT"
    REVIEW = "REVIEW"
    SENT_TO_BANK = "SENT_TO_BANK"
    COMPLETED = "COMPLETED"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Processes(Base):

    __tablename__ = TABLE_NAME

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    bank_id: Mapped[int] = mapped_column(Integer, ForeignKey("banks.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    term: Mapped[int] = mapped_column(Integer)
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    stage: Mapped[str] = mapped_column(String(20), default=ProcessStage.FORM.value)
    form_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    sign_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    def create(user_id, bank_id, amount, term, rate):

        statement = (
            insert(Processes)
            .values(
                user_id=user_id,
                bank_id=bank_id,
                amount=amount,
                term=term,
                rate=rate,
            )
            .returning(Processes)
        )

        return db_session.query(statement=statement)

    def get_by_id(process_id):

        statement = (
            select(Processes)
            .where(Processes.id == process_id)
            .limit(1)
        )

        return db_session.query(statement=statement)

    def list_by_user(user_id):

        statement = (
            select(Processes)
            .where(Processes.user_id == user_id)
            .order_by(Processes.created_at.desc())
        )

        return db_session.query(statement=statement, many=True)

    