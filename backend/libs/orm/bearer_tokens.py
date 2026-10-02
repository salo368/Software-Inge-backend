from sqlalchemy import DateTime, String, insert, select, update
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base

TABLE_NAME = "bearer_tokens"

class BearerTokens(Base):

    __tablename__ = TABLE_NAME

    id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String())
    token_hash: Mapped[str] = mapped_column(String())
    expires_at = mapped_column(DateTime())
    revoked_at = mapped_column(DateTime())
    created_at = mapped_column(DateTime())

    def create(user_id, token_hash, expires_at):

        statement = (
            insert(BearerTokens)
            .values(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
            .returning(BearerTokens)
        )

        return db_session.query(statement=statement)

    def get_by_hash(token_hash):

        statement = (
            select(BearerTokens)
            .where(BearerTokens.token_hash == token_hash)
            .limit(1)
        )

        return db_session.query(statement=statement)

    def update_by_id(id, values):

        statement = (
            update(BearerTokens)
            .where(BearerTokens.id == id)
            .values(**values)
            .returning(BearerTokens)
        )

        return db_session.query(statement=statement)
