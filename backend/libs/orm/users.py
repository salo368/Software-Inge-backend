from sqlalchemy import DateTime, String, insert, select
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base

TABLE_NAME = "users"

class Users(Base):

    __tablename__ = TABLE_NAME

    id: Mapped[str] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String())
    full_name: Mapped[str] = mapped_column(String())
    created_at = mapped_column(DateTime())
    updated_at = mapped_column(DateTime())

    def create(email, full_name):

        statement = (
            insert(Users)
            .values(
                email=email.strip().lower(),
                full_name=full_name.strip(),
            )
            .returning(Users)
        )

        return db_session.query(statement=statement)

    def get_by_email(email):

        statement = (
            select(Users)
            .where(Users.email == email.strip().lower())
            .limit(1)
        )

        return db_session.query(statement=statement)

    def get_by_id(user_id):

        statement = (
            select(Users)
            .where(Users.id == user_id)
            .limit(1)
        )

        return db_session.query(statement=statement)
