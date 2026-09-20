import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base

STAGES = ("review", "identity", "drawing", "otp", "signed")
EVIDENCE_TYPES = ("cedula_front", "cedula_back", "face", "signature")

OTP_TTL = timedelta(minutes=10)
MAX_OTP_ATTEMPTS = 3


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Signatures(Base):
    __tablename__ = "signatures"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    process_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("processes.id", ondelete="CASCADE")
    )
    token: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(320))
    stage: Mapped[str] = mapped_column(String(20), default="review")
    pdf_key: Mapped[str] = mapped_column(Text)
    page: Mapped[int] = mapped_column(Integer, default=1)
    pos_x: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    pos_y: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    cedula_front_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cedula_back_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    face_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signature_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signed_pdf_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    otp_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    otp_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    otp_attempts: Mapped[int] = mapped_column(Integer, default=0)
    doc_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    @property
    def uploads(self) -> dict[str, bool]:
        return {t: bool(getattr(self, f"{t}_key")) for t in EVIDENCE_TYPES}

    @property
    def masked_email(self) -> str:
        local, _, domain = self.email.partition("@")
        return f"{local[:2]}***@{domain}"

    def public_dict(self) -> dict:
        return {
            "token": self.token,
            "process_id": str(self.process_id),
            "stage": self.stage,
            "page": self.page,
            "x": float(self.pos_x),
            "y": float(self.pos_y),
            "email_masked": self.masked_email,
            "uploads": self.uploads,
            "doc_hash": self.doc_hash,
            "signed_at": self.signed_at.isoformat() if self.signed_at else None,
        }

    @classmethod
    def get_by_token(cls, token: str):
        stmt = select(cls).where(cls.token == token).limit(1)
        return db_session.session.execute(stmt).scalars().first()

    @classmethod
    def get_active_for_process(cls, process_id: UUID):
        stmt = (
            select(cls)
            .where(cls.process_id == process_id)
            .order_by(cls.created_at.desc())
            .limit(1)
        )
        return db_session.session.execute(stmt).scalars().first()

    @classmethod
    def create(cls, *, process_id: UUID, email: str, pdf_key: str,
               page: int, pos_x: float, pos_y: float, token: str):
        row = cls(
            process_id=process_id,
            token=token,
            email=email.strip().lower(),
            pdf_key=pdf_key,
            page=page,
            pos_x=Decimal(str(pos_x)),
            pos_y=Decimal(str(pos_y)),
        )
        db_session.session.add(row)
        db_session.session.flush()
        return row

    def resolved_stage(self) -> str:
        """Stage implied by the evidence gathered so far.

        Kept separate from `stage` so a rejected photo can pull the ceremony
        back without the caller having to reason about the order.
        """
        if self.stage == "signed":
            return "signed"
        if self.signature_key:
            return "otp"
        if self.cedula_front_key and self.cedula_back_key and self.face_key:
            return "drawing"
        return "identity"

    def attach_evidence(self, evidence_type: str, key: str | None) -> None:
        setattr(self, f"{evidence_type}_key", key)
        self.stage = self.resolved_stage()
        db_session.session.flush()

    def issue_otp(self) -> str:
        otp = f"{secrets.randbelow(1_000_000):06d}"
        self.otp_hash = _hash(otp)
        self.otp_expires_at = _utcnow() + OTP_TTL
        self.otp_attempts = 0
        self.stage = "otp"
        db_session.session.flush()
        return otp

    def otp_matches(self, otp: str) -> bool:
        return bool(self.otp_hash) and _hash(otp) == self.otp_hash

    def register_failed_attempt(self) -> int:
        self.otp_attempts += 1
        db_session.session.flush()
        return MAX_OTP_ATTEMPTS - self.otp_attempts

    def mark_signed(self, *, signed_pdf_key: str, doc_hash: str, signed_at: datetime) -> None:
        self.stage = "signed"
        self.signed_pdf_key = signed_pdf_key
        self.doc_hash = doc_hash
        self.signed_at = signed_at
        self.otp_hash = None
        db_session.session.flush()
