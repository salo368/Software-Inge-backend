from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Users(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    def public_dict(self) -> dict:
        d = self.to_dict()
        d.pop("password_hash", None)
        return d

    @classmethod
    def get_by_email(cls, email: str):
        stmt = select(cls).where(cls.email == email.strip().lower()).limit(1)
        return db_session.session.execute(stmt).scalars().first()

    @classmethod
    def get_by_id(cls, user_id):
        return db_session.session.get(cls, user_id)

    @classmethod
    def create(cls, *, email: str, password_hash: str, full_name: str):
        user = cls(
            email=email.strip().lower(),
            password_hash=password_hash,
            full_name=full_name.strip(),
        )
        db_session.session.add(user)
        db_session.session.flush()
        return user
