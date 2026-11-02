from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, insert, select
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base


class SignatureStage(str, Enum):
    FORM = "FORM"
    BIOMETRICS = "BIOMETRICS"
    SIGNATURE = "SIGNATURE"
    OTP = "OTP"
    SIGNED = "SIGNED"


class Signatures(Base):
    __tablename__ = "signatures"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    stage: Mapped[str] = mapped_column(String(20))
    doc_s3_key: Mapped[str] = mapped_column(String(300), unique=True)
    sign_location: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def create(doc_s3_key, sign_location):

        statement = (
            insert(Signatures)
            .values(
                doc_s3_key=doc_s3_key,
                sign_location=sign_location,
                stage=SignatureStage.FORM.value,
            )
            .returning(Signatures)
        )

        return db_session.query(statement=statement)

    def get_by_id(signature_id):

        statement = (
            select(Signatures)
            .where(Signatures.id == signature_id)
            .limit(1)
        )

        return db_session.query(statement=statement)
