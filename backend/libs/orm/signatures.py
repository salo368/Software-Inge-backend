from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Integer, String, insert, select, text, update
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base

# Matches the SQS DelaySeconds the `check_signature_timeout` worker is
# queued with in create_signature -- keep both in lockstep.
SIGNING_WINDOW = timedelta(minutes=15)

OTP_TTL = timedelta(minutes=2)
MAX_OTP_TRIES = 3

# Matches the SQS DelaySeconds check_signing_timeout is queued with in
# resolve_otp -- a short safety net so a sign_doc crash/hang doesn't
# leave a signature stuck at SIGNING forever without SIGNING_WINDOW's
# 15-minute worker touching it (it deliberately skips this stage).
SIGNING_TIMEOUT = timedelta(seconds=60)


class SignatureStage(str, Enum):
    FORM = "FORM"
    BIOMETRICS = "BIOMETRICS"
    SIGNATURE = "SIGNATURE"
    OTP = "OTP"
    SIGNING = "SIGNING"
    SIGNED = "SIGNED"
    FAILED = "FAILED"


class BiometricType(str, Enum):
    ID_FRONT = "ID_FRONT"
    ID_BACK = "ID_BACK"
    FACE = "FACE"


BIOMETRIC_COLUMNS = {
    BiometricType.ID_FRONT.value: "id_front_s3_key",
    BiometricType.ID_BACK.value: "id_back_s3_key",
    BiometricType.FACE.value: "id_face_s3_key",
}


class Signatures(Base):
    __tablename__ = "signatures"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    stage: Mapped[str] = mapped_column(String(20))
    doc_s3_key: Mapped[str] = mapped_column(String(300), unique=True)
    sign_location: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    signatory: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    id_front_s3_key: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    id_back_s3_key: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    id_face_s3_key: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    draw_s3_key: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    signed_s3_key: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    signing_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    otp_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    otp_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    otp_tries: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def create(doc_s3_key, sign_location, signatory):

        statement = (
            insert(Signatures)
            .values(
                doc_s3_key=doc_s3_key,
                sign_location=sign_location,
                signatory=signatory,
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

    def set_email(signature_id, email):

        statement = (
            update(Signatures)
            .where(Signatures.id == signature_id)
            .values(
                email=email,
                stage=SignatureStage.BIOMETRICS.value,
            )
            .returning(Signatures)
        )

        return db_session.query(statement=statement)

    def set_biometric_key(signature_id, biometric_type, s3_key):

        column = BIOMETRIC_COLUMNS[biometric_type]

        statement = (
            update(Signatures)
            .where(Signatures.id == signature_id)
            .values(**{column: s3_key})
            .returning(Signatures)
        )

        return db_session.query(statement=statement)

    def advance_to_signature_stage(signature_id):

        statement = (
            update(Signatures)
            .where(Signatures.id == signature_id)
            .values(stage=SignatureStage.SIGNATURE.value)
            .returning(Signatures)
        )

        return db_session.query(statement=statement)

    def set_draw_key(signature_id, draw_s3_key):

        statement = (
            update(Signatures)
            .where(Signatures.id == signature_id)
            .values(
                draw_s3_key=draw_s3_key,
                stage=SignatureStage.OTP.value,
            )
            .returning(Signatures)
        )

        return db_session.query(statement=statement)

    def set_otp(signature_id, otp_hash):

        statement = (
            update(Signatures)
            .where(Signatures.id == signature_id)
            .values(
                otp_hash=otp_hash,
                otp_at=text("NOW()"),
                otp_tries=0,
            )
            .returning(Signatures)
        )

        return db_session.query(statement=statement)

    def register_failed_otp_attempt(signature_id):

        statement = (
            update(Signatures)
            .where(Signatures.id == signature_id)
            .values(otp_tries=Signatures.otp_tries + 1)
            .returning(Signatures)
        )

        return db_session.query(statement=statement)

    def start_signing(signature_id, signing_data):

        statement = (
            update(Signatures)
            .where(Signatures.id == signature_id)
            .values(
                stage=SignatureStage.SIGNING.value,
                otp_hash=None,
                signing_data=signing_data,
            )
            .returning(Signatures)
        )

        return db_session.query(statement=statement)

    def mark_signed(signature_id, signed_s3_key):

        statement = (
            update(Signatures)
            .where(Signatures.id == signature_id)
            .values(
                stage=SignatureStage.SIGNED.value,
                signed_s3_key=signed_s3_key,
            )
            .returning(Signatures)
        )

        return db_session.query(statement=statement)

    def mark_failed(signature_id):

        statement = (
            update(Signatures)
            .where(Signatures.id == signature_id)
            .values(stage=SignatureStage.FAILED.value)
            .returning(Signatures)
        )

        return db_session.query(statement=statement)
