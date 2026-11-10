from uuid import UUID

from sqlalchemy import DateTime, String, insert, select, update
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base

TABLE_NAME = "user_bearer_tokens"

class UserBearerTokens(Base):

    __tablename__ = TABLE_NAME

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    token_hash: Mapped[str] = mapped_column(String())
    expires_at = mapped_column(DateTime())
    revoked_at = mapped_column(DateTime())
    created_at = mapped_column(DateTime())

    def create(user_id, token_hash, expires_at):

        statement = (
            insert(UserBearerTokens)
            .values(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
            .returning(UserBearerTokens)
        )

        return db_session.query(statement=statement)

    def get_by_hash(token_hash):

        statement = (
            select(UserBearerTokens)
            .where(UserBearerTokens.token_hash == token_hash)
            .limit(1)
        )

        return db_session.query(statement=statement)

    def update_by_id(id, values):

        statement = (
            update(UserBearerTokens)
            .where(UserBearerTokens.id == id)
            .values(**values)
            .returning(UserBearerTokens)
        )

        return db_session.query(statement=statement)
