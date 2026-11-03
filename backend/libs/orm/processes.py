from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Integer, Numeric, String, insert, select, text, update
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


class Processes(Base):

    __tablename__ = TABLE_NAME

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    bank_id: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    term: Mapped[int] = mapped_column(Integer)
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    stage: Mapped[str] = mapped_column(String(20))
    submitted_form: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    signature_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def create(user_id, bank_id, amount, term, rate):

        statement = (
            insert(Processes)
            .values(
                user_id=user_id,
                bank_id=bank_id,
                amount=amount,
                term=term,
                rate=rate,
                stage=ProcessStage.FORM.value,
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

    def set_submitted_form(process_id, submitted_form):

        statement = (
            update(Processes)
            .where(Processes.id == process_id)
            .values(
                submitted_form=submitted_form,
                stage=ProcessStage.DOCUMENTS.value,
                updated_at=text("NOW()"),
            )
            .returning(Processes)
        )

        return db_session.query(statement=statement)

    def set_signature_id(process_id, signature_id):

        statement = (
            update(Processes)
            .where(Processes.id == process_id)
            .values(
                signature_id=signature_id,
                stage=ProcessStage.SIGNATURE.value,
                updated_at=text("NOW()"),
            )
            .returning(Processes)
        )

        return db_session.query(statement=statement)
