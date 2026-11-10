from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Integer, Numeric, String, and_, cast, func, insert, or_, select, text, update
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base
from libs.orm.like import LIKE_ESCAPE, prefix_pattern

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

    def get_by_id_for_update(process_id):
  
        statement = (
            select(Processes)
            .where(Processes.id == process_id)
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

        return db_session.query(statement=statement)

    def get_by_signature_id(signature_id):

        statement = (
            select(Processes)
            .where(Processes.signature_id == signature_id)
            .limit(1)
        )

        return db_session.query(statement=statement)

    def get_by_signature_id_for_update(signature_id):

        statement = (
            select(Processes)
            .where(Processes.signature_id == signature_id)
            .limit(1)
            .with_for_update()
            .execution_options(populate_existing=True)
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

    def advance_to_payment(process_id):

        statement = (
            update(Processes)
            .where(Processes.id == process_id)
            .values(
                stage=ProcessStage.PAYMENT.value,
                updated_at=text("NOW()"),
            )
            .returning(Processes)
        )

        return db_session.query(statement=statement)

    def advance_to_review(process_id):

        statement = (
            update(Processes)
            .where(Processes.id == process_id)
            .values(
                stage=ProcessStage.REVIEW.value,
                updated_at=text("NOW()"),
            )
            .returning(Processes)
        )

        return db_session.query(statement=statement)

    def advance_to_sent_to_bank(process_id):

        statement = (
            update(Processes)
            .where(Processes.id == process_id)
            .values(
                stage=ProcessStage.SENT_TO_BANK.value,
                updated_at=text("NOW()"),
            )
            .returning(Processes)
        )

        return db_session.query(statement=statement)

    def advance_to_completed(process_id):

        statement = (
            update(Processes)
            .where(Processes.id == process_id)
            .values(
                stage=ProcessStage.COMPLETED.value,
                updated_at=text("NOW()"),
            )
            .returning(Processes)
        )

        return db_session.query(statement=statement)

    def _list_conditions(bank_id, stages, search):

        conditions = []

        if bank_id is not None:
            conditions.append(Processes.bank_id == bank_id)

        if stages:
            conditions.append(cast(Processes.stage, String).in_(stages))

        if search:
            conditions.append(Processes._search_filter(search))

        return conditions

    SEARCH_FIELDS = ("name", "second_name", "last_name", "second_last_name", "email", "document_number")
    MAX_SEARCH_WORDS = 6

    def _search_filter(search):

        words = search.split()[:Processes.MAX_SEARCH_WORDS]

        return and_(*(
            or_(*(
                Processes.submitted_form[key].astext.ilike(prefix_pattern(word), escape=LIKE_ESCAPE)
                for key in Processes.SEARCH_FIELDS
            ))
            for word in words
        ))

    def search(bank_id, stages, search, limit, offset):

        statement = (
            select(Processes)
            .where(*Processes._list_conditions(bank_id, stages, search))
            .order_by(Processes.created_at.desc(), Processes.id)
            .limit(limit)
            .offset(offset)
        )

        return db_session.query(statement=statement, many=True)

    def count_search(bank_id, stages, search):

        statement = (
            select(func.count())
            .select_from(Processes)
            .where(*Processes._list_conditions(bank_id, stages, search))
        )

        return db_session.query(statement=statement)
