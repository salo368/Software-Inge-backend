from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Files(Base):
    __tablename__ = "files"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    process_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("processes.id", ondelete="CASCADE")
    )
    file_type: Mapped[str] = mapped_column(String(50))
    s3_key: Mapped[str] = mapped_column(Text, unique=True)
    original_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def public_dict(self) -> dict:
        return {
            "id": str(self.id),
            "file_type": self.file_type,
            "s3_key": self.s3_key,
            "original_name": self.original_name,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
            "uploaded_at": self.uploaded_at.isoformat(),
        }

    @classmethod
    def get_by_id(cls, file_id: UUID):
        return db_session.session.get(cls, file_id)

    @classmethod
    def get_by_key(cls, s3_key: str):
        stmt = select(cls).where(cls.s3_key == s3_key).limit(1)
        return db_session.session.execute(stmt).scalars().first()

    @classmethod
    def list_by_process(cls, process_id: UUID):
        stmt = select(cls).where(cls.process_id == process_id).order_by(cls.uploaded_at.desc())
        return list(db_session.session.execute(stmt).scalars().all())

    @classmethod
    def register_from_s3(cls, *, process_id: UUID, file_type: str, s3_key: str,
                          original_name: Optional[str] = None,
                          size_bytes: Optional[int] = None,
                          content_type: Optional[str] = None):
        row = cls(
            process_id=process_id,
            file_type=file_type,
            s3_key=s3_key,
            original_name=original_name,
            size_bytes=size_bytes,
            content_type=content_type,
        )
        db_session.session.add(row)
        db_session.session.flush()
        return row
