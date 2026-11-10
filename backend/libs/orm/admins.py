from uuid import UUID

from sqlalchemy import DateTime, String, insert, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base

TABLE_NAME = "admins"

class Admins(Base):

    __tablename__ = TABLE_NAME

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String())
    full_name: Mapped[str] = mapped_column(String())
    created_at = mapped_column(DateTime())
    updated_at = mapped_column(DateTime())

    def create(email, full_name):

        statement = (
            insert(Admins)
            .values(
                email=email.strip().lower(),
                full_name=full_name.strip(),
            )
            .returning(Admins)
        )

        return db_session.query(statement=statement)

    def get_by_email(email):

        statement = (
            select(Admins)
            .where(Admins.email == email.strip().lower())
            .limit(1)
        )

        return db_session.query(statement=statement)

    def get_by_id(admin_id):

        statement = (
            select(Admins)
            .where(Admins.id == admin_id)
            .limit(1)
        )

        return db_session.query(statement=statement)
