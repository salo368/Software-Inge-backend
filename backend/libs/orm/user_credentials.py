from sqlalchemy import DateTime, String, insert, select
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base

TABLE_NAME = "user_credentials"

class UserCredentials(Base):

    __tablename__ = TABLE_NAME

    user_id: Mapped[str] = mapped_column(primary_key=True)
    password_hash: Mapped[str] = mapped_column(String())
    created_at = mapped_column(DateTime())
    updated_at = mapped_column(DateTime())

    def create(user_id, password_hash):

        statement = (
            insert(UserCredentials)
            .values(
                user_id=user_id,
                password_hash=password_hash,
            )
            .returning(UserCredentials)
        )

        return db_session.query(statement=statement)

    def get_by_user_id(user_id):

        statement = (
            select(UserCredentials)
            .where(UserCredentials.user_id == user_id)
            .limit(1)
        )

        return db_session.query(statement=statement)
