from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import Numeric, Text, func, insert, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base


class Payments(Base):
    __tablename__ = "payments"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    process_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    s3_file: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def create(process_id, amount, s3_file):

        statement = (
            insert(Payments)
            .values(
                process_id=process_id,
                amount=amount,
                s3_file=s3_file,
            )
            .returning(Payments)
        )

        return db_session.query(statement=statement)

    def lock_process(process_id):
        """Transaction-scoped advisory lock keyed by process.

        Payments can't row-lock `processes` (owned by another service), so
        concurrent payments for the same process serialize here instead:
        the loser waits until the winner commits, then sees its payment.
        """

        statement = select(func.pg_advisory_xact_lock(func.hashtext(str(process_id))))

        return db_session.query(statement=statement)

    def list_by_process(process_id):

        statement = (
            select(Payments)
            .where(Payments.process_id == process_id)
        )

        return db_session.query(statement=statement, many=True)
