from uuid import UUID

from sqlalchemy import DateTime, String, insert, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base

TABLE_NAME = "admin_credentials"

class AdminCredentials(Base):

    __tablename__ = TABLE_NAME

    admin_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String())
    created_at = mapped_column(DateTime())
    updated_at = mapped_column(DateTime())

    def create(admin_id, password_hash):

        statement = (
            insert(AdminCredentials)
            .values(
                admin_id=admin_id,
                password_hash=password_hash,
            )
            .returning(AdminCredentials)
        )

        return db_session.query(statement=statement)

    def get_by_admin_id(admin_id):

        statement = (
            select(AdminCredentials)
            .where(AdminCredentials.admin_id == admin_id)
            .limit(1)
        )

        return db_session.query(statement=statement)
