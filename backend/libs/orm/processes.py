from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, insert, select, update
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base

TABLE_NAME = "processes"

STAGES = ("form", "documents", "signature", "payment", "done")


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
    stage: Mapped[str] = mapped_column(String(20), default="form")
    form_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    sign_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    def get_by_id(process_id):

        statement = (
            select(Processes)
            .where(Processes.id == process_id)
            .limit(1)
        )

        return db_session.query(statement=statement)

    def get_by_sign_id(sign_id):

        if not sign_id:
            return None

        statement = (
            select(Processes)
            .where(Processes.sign_id == sign_id)
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

    def mark_signed_at(self, signed_at):

        if self.signed_at is not None:
            return

        statement = (
            update(Processes)
            .where(Processes.id == self.id)
            .values(signed_at=signed_at)
            .returning(Processes)
        )

        db_session.query(statement=statement)
        self.signed_at = signed_at

    def advance_to(self, next_stage):

        if next_stage not in STAGES:
            raise ValueError(f"invalid stage {next_stage!r}")

        values = {"stage": next_stage}
        now = _utcnow()

        if next_stage == "payment" and self.signed_at is None:
            values["signed_at"] = now
        elif next_stage == "done":
            values["paid_at"] = now
            values["completed_at"] = now

        statement = (
            update(Processes)
            .where(Processes.id == self.id)
            .values(**values)
            .returning(Processes)
        )

        db_session.query(statement=statement)
        for key, value in values.items():
            setattr(self, key, value)
