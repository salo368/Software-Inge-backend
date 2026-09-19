from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import CHAR, DateTime, ForeignKey, select, update
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base


class BearerTokens(Base):
    __tablename__ = "bearer_tokens"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def is_alive(self) -> bool:
        return self.revoked_at is None and self.expires_at > datetime.now(timezone.utc)

    @classmethod
    def get_by_hash(cls, token_hash: str):
        stmt = select(cls).where(cls.token_hash == token_hash).limit(1)
        return db_session.session.execute(stmt).scalars().first()

    @classmethod
    def create(cls, *, user_id: UUID, token_hash: str, expires_at: datetime):
        row = cls(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        db_session.session.add(row)
        db_session.session.flush()
        return row

    @classmethod
    def revoke(cls, token_id: UUID) -> bool:
        stmt = (
            update(cls)
            .where(cls.id == token_id, cls.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
        return (db_session.session.execute(stmt).rowcount or 0) > 0
