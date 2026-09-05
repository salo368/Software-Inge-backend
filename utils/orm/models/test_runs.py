from datetime import datetime
from typing import Self

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from utils.orm.db import get_session
from utils.orm.model import Model


class TestRuns(Model):
    __tablename__ = "test_runs"

    status: Mapped[str] = mapped_column(String(20), nullable=False)
    results: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @classmethod
    def get_recent(cls, limit: int = 20) -> list[Self]:
        with get_session() as s:
            objs = s.query(cls).order_by(cls.id.desc()).limit(limit).all()
            for o in objs:
                s.expunge(o)
            return objs
