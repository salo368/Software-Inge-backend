from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, String, Text, insert, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base


class FileType(str, Enum):
    TAX_DECLARATION = "TAX_DECLARATION"
    RUT = "RUT"
    BANK_CERT = "BANK_CERT"
    INVESTMENT_ORDER = "INVESTMENT_ORDER"


class Files(Base):
    __tablename__ = "files"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    process_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    file_type: Mapped[str] = mapped_column(String(50))
    s3_key: Mapped[str] = mapped_column(Text, unique=True)
    original_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def create(process_id, file_type, s3_key, original_name=None, size_bytes=None, content_type=None):

        statement = (
            insert(Files)
            .values(
                process_id=process_id,
                file_type=file_type,
                s3_key=s3_key,
                original_name=original_name,
                size_bytes=size_bytes,
                content_type=content_type,
            )
            .returning(Files)
        )

        return db_session.query(statement=statement)

    def list_by_process(process_id):

        statement = (
            select(Files)
            .where(Files.process_id == process_id)
            .order_by(Files.uploaded_at.desc())
        )

        return db_session.query(statement=statement, many=True)
