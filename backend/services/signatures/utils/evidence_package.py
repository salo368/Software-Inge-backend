"""Builds the evidence-package.json bundled with every signed PDF.

Rationale: PAdES-B alone binds the signer's cert to the document hash,
but not to *who was really at the keyboard*. The audit trail must
combine:

    * the identity evidences the signer uploaded (ID front/back + face);
    * the explicit consent event (Ley 527 §7);
    * the OTP challenge that closed the loop between the sign URL and
      the email of record;
    * the cryptographic outputs of `sign` (hashes + cert serial + PEM).

We serialise all of that into a single JSON document that lives next to
the signed PDF at `transactions/{sign_id}/evidence-package.json`. The
`verify` endpoint reads both, cross-checks the hashes, and answers
whether the PDF has been tampered with AND whether the ceremony was
properly executed.

The JSON schema is intentionally flat and self-describing: any auditor
can read it without needing our source code. It embeds the S3 keys of
the evidence photos rather than the bytes so the package stays small
(~2 KB); the photos are downloaded separately by the verifier.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


_PACKAGE_VERSION = "1.0"


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Postgres returns naive UTC by default; force awareness so the
        # ISO string carries the offset.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def build_evidence_package(
    *,
    signature,
    signed_pdf_key: str,
    original_pdf_key: str,
    cert_pem: str,
) -> dict:
    """Assembles the evidence-package JSON from the persisted ceremony
    row + the byproducts of the `sign` invocation.

    Arguments:
        signature: the Signatures ORM row (already at stage=`signed`).
        signed_pdf_key: S3 key where the signed PDF was uploaded.
        original_pdf_key: S3 key of the source PDF (from `create`).
        cert_pem: leaf certificate PEM issued for this transaction.

    Returns a JSON-serialisable dict. `mark_signed` should have already
    stamped `hash_signed`, `cert_serial` and `signed_at` on the row
    before this is called.
    """
    return {
        "schema_version": _PACKAGE_VERSION,
        "generated_at": _iso(datetime.now(timezone.utc)),
        # ---- Ceremony identity ------------------------------------------
        "sign_id": signature.sign_id,
        "service_caller": signature.service_caller,
        # ---- Signer -----------------------------------------------------
        "signer": {
            "email": signature.signer_email,
            "email_masked": signature.masked_email,
            "name": signature.signer_name,
        },
        # ---- Document ---------------------------------------------------
        "document": {
            "original_key": original_pdf_key,
            "signed_key": signed_pdf_key,
            "hash_original": signature.hash_original,
            "hash_signed": signature.hash_signed,
            "signature_location": signature.signature_location,
        },
        # ---- Identity evidences ----------------------------------------
        # Keys only, not bytes. Auditor downloads them from S3 as needed;
        # `uploads_state` mirrors what the frontend saw during the wizard.
        "evidences": {
            "uploads_state": signature.uploads_state,
        },
        # ---- Consent (Ley 527 §7) --------------------------------------
        "consent": {
            "given_at": _iso(signature.consent_given_at),
            "terms_version": signature.consent_terms_version,
        },
        # ---- OTP challenge outcome -------------------------------------
        # `signed_at` is when start_signing() fired; that transition only
        # happens after a correct OTP, so it doubles as the verification
        # timestamp. The plaintext OTP is never stored, so nothing else
        # is recorded here.
        "otp": {
            "verified_at": _iso(signature.signed_at),
            "max_attempts": None,  # filled in by caller if desired
        },
        # ---- Cryptographic artefacts -----------------------------------
        "signature": {
            "algorithm": "PAdES-B baseline",
            "hash_algorithm": "sha256",
            "cert_serial": signature.cert_serial,
            "cert_pem": cert_pem,
            "signed_at": _iso(signature.signed_at),
        },
        # ---- Timing -----------------------------------------------------
        "timing": {
            "created_at": _iso(signature.created_at),
            "expires_at": _iso(signature.expires_at),
        },
    }
