from datetime import datetime
from typing import Self

from sqlalchemy import BigInteger, CHAR, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from utils.orm.model import Model


class BearerTokens(Model):
    __tablename__ = "bearer_tokens"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @classmethod
    def get_by_token_hash(cls, token_hash: str) -> Self | None:
        return cls._get_one(token_hash=token_hash)
