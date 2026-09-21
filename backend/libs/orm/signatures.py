"""Signature ceremony (v2 — generic signing service).

This model is intentionally decoupled from `processes`, `forms`, `banks`
and `files`: the `signatures` service accepts any PDF via a presigned
URL and drives the ceremony to completion without knowing what business
flow triggered it. The caller (e.g. `processes.create_signature_ceremony`)
receives `sign_id` back and stores it wherever it needs to.

Lifecycle (stage transitions, happy path):

    created  --upload/validate any evidence-->  identity
    identity --all 4 evidences validated---->   consent
    consent  --explicit consent captured---->   otp
    otp      --OTP verified------------------>  signing
    signing  --async `sign` lambda done----->   signed

Terminal states outside the happy path:

    * `expired` -- reached `expires_at` while stage was not terminal
    * `failed`  -- the internal `sign` lambda raised

Auth model: `sign_id` (32-byte urlsafe token, ~256 bits of entropy) is
BOTH the primary key AND the capability. Anyone who holds the sign URL
that embeds it can operate the ceremony. `POST /signatures` (which
issues sign_ids) is service-to-service (`X-Service-Key`), so only
trusted backend services can spawn ceremonies. Everything downstream
of it is authorized by "you have the sign_id".
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from libs.core.db import db_session
from libs.orm.base import Base

STAGES = (
    "created",
    "identity",
    "consent",
    "otp",
    "signing",
    "signed",
    "expired",
    "failed",
)
EVIDENCE_TYPES = ("id_front", "id_back", "face", "signature")
# Evidence types that need explicit validation before counting as ready.
# `signature` (the drawn canvas PNG) is not biometrically validated; it
# just needs to be uploaded.
VALIDATED_EVIDENCES = ("id_front", "id_back", "face")

OTP_TTL = timedelta(minutes=10)
MAX_OTP_ATTEMPTS = 5
CEREMONY_TTL = timedelta(hours=24)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_sign_id() -> str:
    """32-byte urlsafe token. Fits in VARCHAR(64) (43 chars base64url)."""
    return secrets.token_urlsafe(32)


class Signatures(Base):
    __tablename__ = "signatures"

    sign_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_sign_id)
    signer_email: Mapped[str] = mapped_column(String(320))
    signer_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # {"page": int (1-based), "x_pct": float 0-100, "y_pct": float 0-100}
    signature_location: Mapped[dict] = mapped_column(JSONB)
    callback_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    service_caller: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    hash_original: Mapped[str] = mapped_column(String(64))
    hash_signed: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    cert_serial: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    stage: Mapped[str] = mapped_column(String(20), default="created")
    # Evidence keys (relative to the signatures bucket).
    id_front_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    id_back_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    face_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signature_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Rekognition validation timestamps.
    id_front_validated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    id_back_validated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    face_validated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Explicit consent step (Ley 527).
    consent_given_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consent_terms_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # OTP challenge.
    otp_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    otp_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    otp_attempts: Mapped[int] = mapped_column(Integer, default=0)
    signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Callback bookkeeping (one-shot; no retry).
    callback_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    callback_failed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    callback_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------
    @property
    def masked_email(self) -> str:
        local, _, domain = self.signer_email.partition("@")
        return f"{local[:2]}***@{domain}"

    @property
    def uploads_state(self) -> dict[str, dict]:
        """Per-evidence dict, ready for the frontend to render the wizard.

        Each entry has:
            uploaded (bool)
            validated (bool | None)  -- None for `signature` (no crypto check)
            key (str | None)
            validated_at (str ISO | None)
        """
        state: dict[str, dict] = {}
        for t in EVIDENCE_TYPES:
            key = getattr(self, f"{t}_key")
            state[t] = {"uploaded": bool(key), "key": key}
            if t in VALIDATED_EVIDENCES:
                validated_at = getattr(self, f"{t}_validated_at")
                state[t]["validated"] = validated_at is not None
                state[t]["validated_at"] = (
                    validated_at.isoformat() if validated_at else None
                )
            else:
                state[t]["validated"] = None
                state[t]["validated_at"] = None
        return state

    @property
    def all_evidences_ready(self) -> bool:
        """True when the 3 biometric evidences are validated AND the drawn
        signature is uploaded. Gate for advancing to `consent`."""
        return (
            self.id_front_validated_at is not None
            and self.id_back_validated_at is not None
            and self.face_validated_at is not None
            and self.signature_key is not None
        )

    def public_dict(self) -> dict:
        """Shape returned by `GET /signatures/{sign_id}`. Safe to expose to
        the signer over the sign URL."""
        return {
            "sign_id": self.sign_id,
            "signer_email_masked": self.masked_email,
            "signature_location": self.signature_location,
            "stage": self.stage,
            "uploads_state": self.uploads_state,
            "consent": {
                "given": self.consent_given_at is not None,
                "given_at": (
                    self.consent_given_at.isoformat() if self.consent_given_at else None
                ),
                "terms_version": self.consent_terms_version,
            },
            "otp": {
                "requested": self.otp_hash is not None,
                "expires_at": (
                    self.otp_expires_at.isoformat() if self.otp_expires_at else None
                ),
                "attempts_left": max(0, MAX_OTP_ATTEMPTS - self.otp_attempts),
            },
            "hash_original": self.hash_original,
            "hash_signed": self.hash_signed,
            "cert_serial": self.cert_serial,
            "signed_at": self.signed_at.isoformat() if self.signed_at else None,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------
    @classmethod
    def get_by_sign_id(cls, sign_id: str):
        return db_session.session.get(cls, sign_id)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------
    @classmethod
    def create(
        cls,
        *,
        signer_email: str,
        signer_name: Optional[str],
        signature_location: dict,
        hash_original: str,
        callback_url: Optional[str] = None,
        service_caller: Optional[str] = None,
        sign_id: Optional[str] = None,
    ):
        """Opens a ceremony. Returns the row.

        `sign_id` can be pre-generated by the caller (recommended when
        the caller needs to reference the sign_id in side effects that
        happen BEFORE persistence, e.g. S3 uploads under
        `transactions/{sign_id}/`). If omitted, a fresh token is
        allocated automatically.
        """
        now = _utcnow()
        row = cls(
            sign_id=sign_id or new_sign_id(),
            signer_email=signer_email.strip().lower(),
            signer_name=signer_name.strip() if signer_name else None,
            signature_location=signature_location,
            hash_original=hash_original,
            callback_url=callback_url,
            service_caller=service_caller,
            stage="created",
            created_at=now,
            updated_at=now,
            expires_at=now + CEREMONY_TTL,
        )
        db_session.session.add(row)
        db_session.session.flush()
        return row

    def resolved_stage(self) -> str:
        """Stage implied by the current column state.

        Terminal states short-circuit (nothing rolls back a `signed` or
        `failed` ceremony). Otherwise we walk forward from the most
        advanced condition met.
        """
        if self.stage in ("signed", "expired", "failed", "signing"):
            return self.stage
        if self.consent_given_at is not None:
            return "otp" if self.otp_hash is not None else "otp"
        if self.all_evidences_ready:
            return "consent"
        any_evidence = any(
            getattr(self, f"{t}_key") is not None for t in EVIDENCE_TYPES
        )
        return "identity" if any_evidence else "created"

    def attach_evidence(self, evidence_type: str, key: Optional[str]) -> None:
        """Records the S3 key for an evidence (or clears it with None).

        Does NOT mark it as validated: for the 3 biometric types the
        validate handlers set the `_validated_at` timestamp explicitly
        after Rekognition succeeds. `signature` has no separate
        validation.
        """
        if evidence_type not in EVIDENCE_TYPES:
            raise ValueError(f"unknown evidence type {evidence_type!r}")
        setattr(self, f"{evidence_type}_key", key)
        # If the evidence was replaced, drop the stale validation stamp
        # so the frontend re-runs the validate call.
        if evidence_type in VALIDATED_EVIDENCES:
            setattr(self, f"{evidence_type}_validated_at", None)
        self.stage = self.resolved_stage()
        db_session.session.flush()

    def mark_evidence_validated(self, evidence_type: str) -> None:
        if evidence_type not in VALIDATED_EVIDENCES:
            raise ValueError(
                f"{evidence_type!r} has no separate validation step"
            )
        setattr(self, f"{evidence_type}_validated_at", _utcnow())
        self.stage = self.resolved_stage()
        db_session.session.flush()

    def give_consent(self, terms_version: str) -> None:
        if not self.all_evidences_ready:
            raise ValueError("cannot consent before all evidences are validated")
        self.consent_given_at = _utcnow()
        self.consent_terms_version = terms_version
        self.stage = "consent"
        db_session.session.flush()

    def issue_otp(self) -> str:
        if self.consent_given_at is None:
            raise ValueError("consent must be given before requesting OTP")
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
        """Increments the attempt counter, returns remaining attempts."""
        self.otp_attempts += 1
        db_session.session.flush()
        return MAX_OTP_ATTEMPTS - self.otp_attempts

    def start_signing(self) -> None:
        """Called after OTP verified, before the internal sign lambda
        starts. `sign` reads this to check idempotency (don't sign twice)."""
        if self.stage not in ("otp",):
            raise ValueError(f"cannot start signing from stage {self.stage!r}")
        self.stage = "signing"
        # OTP hash is single-use; clear it as soon as verification passes.
        self.otp_hash = None
        db_session.session.flush()

    def mark_signed(
        self, *, hash_signed: str, cert_serial: str, signed_at: datetime
    ) -> None:
        self.stage = "signed"
        self.hash_signed = hash_signed
        self.cert_serial = cert_serial
        self.signed_at = signed_at
        db_session.session.flush()

    def mark_failed(self, error: Optional[str] = None) -> None:
        """Records that the async `sign` lambda raised. The stored error
        is for operators; the signer sees only 'failed'."""
        self.stage = "failed"
        if error:
            # Reuse callback_error as a generic failure column so we don't
            # add a schema field for a rare case. Housekeeping / support
            # can grep for stage='failed'.
            self.callback_error = error
        db_session.session.flush()

    def record_callback(
        self, *, sent: bool, error: Optional[str] = None
    ) -> None:
        """Records the one-shot webhook outcome after `sign` completes."""
        now = _utcnow()
        if sent:
            self.callback_sent_at = now
            self.callback_error = None
        else:
            self.callback_failed_at = now
            self.callback_error = error
        db_session.session.flush()
