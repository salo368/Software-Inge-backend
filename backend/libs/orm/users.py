from uuid import UUID

from sqlalchemy import DateTime, String, func, insert, or_, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base
from libs.orm.like import LIKE_ESCAPE, prefix_pattern

TABLE_NAME = "users"

class Users(Base):

    __tablename__ = TABLE_NAME

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
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

    def _search_filter(search):
        """Prefix match (case-insensitive) on full_name or email."""

        pattern = prefix_pattern(search)

        return or_(
            Users.full_name.ilike(pattern, escape=LIKE_ESCAPE),
            Users.email.ilike(pattern, escape=LIKE_ESCAPE),
        )

    def search(search, limit, offset):

        statement = select(Users).order_by(Users.created_at.desc(), Users.id)

        if search:
            statement = statement.where(Users._search_filter(search))

        statement = statement.limit(limit).offset(offset)

        return db_session.query(statement=statement, many=True)

    def count_search(search):

        statement = select(func.count()).select_from(Users)

        if search:
            statement = statement.where(Users._search_filter(search))

        return db_session.query(statement=statement)
