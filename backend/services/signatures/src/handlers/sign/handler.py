"""Internal signing worker.

Invoked asynchronously by `verify_otp` after a correct OTP. Not exposed
over HTTP: `functions.yml` declares no `events`, and IAM only allows the
signatures block itself to `lambda:InvokeFunction` on this ARN. Errors
are absorbed into the ceremony state (`mark_failed`) rather than
propagated, because async invokes have nowhere to surface a 5xx.

Contract:

    Payload (from verify_otp):
        {"sign_id": "<32-byte urlsafe token>"}

    Preconditions:
        row.stage == 'signing'   (set by verify_otp.start_signing())
        row.signature_key is set (drawn signature already uploaded)

    Postconditions on success:
        row.stage == 'signed'
        row.hash_signed, row.cert_serial, row.signed_at set
        S3: evidence-archive/{sign_id}/signed.pdf
        S3: evidence-archive/{sign_id}/evidence-package.json
        Callback POST fired if row.callback_url is set

    The signed PDF and the evidence package live under `evidence-archive/`,
    NOT `transactions/` -- a separate prefix so the bucket's lifecycle rules
    can retain them for 10 years (regulatory requirement) while everything
    else under `transactions/` (original PDF, biometric evidence) keeps
    expiring at 30 days (privacy minimization). See serverless.yml and
    docs/add-signatures-uc3.md.

    Postconditions on failure:
        row.stage == 'failed'
        row.callback_error carries a short reason for support

Pipeline (each step raises SigningError with a stable code on failure;
the top-level except clause turns that into mark_failed + logs):

    1. Load ceremony, gate on stage='signing' (idempotence).
    2. Download source PDF + drawing PNG from S3.
    3. Sanity-check: original PDF hash still matches row.hash_original.
    4. Issue an ephemeral leaf cert via mock_ca.
    5. Stamp the drawing on the PDF at signature_location.
    6. PAdES-B sign the stamped PDF with the leaf cert.
    7. Compute sha256(signed_pdf) as hash_signed.
    8. Upload signed PDF to S3.
    9. Build + upload evidence package JSON.
   10. row.mark_signed(hash_signed, cert_serial, signed_at).
   11. Fire callback (best effort; row.record_callback tracks outcome).

Steps 4 (cert issuance) and 6 (PAdES signing) are the heavy CPU-bound
work; hence memorySize=2048 and timeout=300 in function.yml.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Optional

import boto3
import requests

from libs.core.db import db_session
from libs.core.logger import Logger
from libs.orm.signatures import Signatures

from utils.evidence_package import build_evidence_package
from utils.mock_ca import issue_transaction_cert, sign_pdf_pades_b
from utils.stamp import stamp_drawing_on_pdf


SIGNATURES_BUCKET = os.environ["SIGNATURES_BUCKET"]

# Callback total budget: HTTP connect + read + retry, in seconds. Short
# enough that a slow caller doesn't burn Lambda time, long enough for
# a normal API Gateway roundtrip.
_CALLBACK_TIMEOUT_S = 10


class SigningError(Exception):
    """Stable error codes for signing failures.

    The `code` attribute is what ends up in row.callback_error for
    support to grep on. `detail` is a human-readable extension.
    """

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _s3():
    return boto3.client("s3")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _get_object(key: str) -> bytes:
    try:
        return _s3().get_object(Bucket=SIGNATURES_BUCKET, Key=key)["Body"].read()
    except Exception as e:
        raise SigningError("s3_get_failed", f"key={key}: {e}") from e


def _put_object(key: str, body: bytes, content_type: str) -> None:
    try:
        _s3().put_object(
            Bucket=SIGNATURES_BUCKET,
            Key=key,
            Body=body,
            ContentType=content_type,
        )
    except Exception as e:
        raise SigningError("s3_put_failed", f"key={key}: {e}") from e


def _fire_callback(row: Signatures) -> None:
    """POSTs the ceremony outcome to `row.callback_url`. Records the
    outcome on the row via `record_callback`. Never raises.

    The payload is intentionally minimal: sign_id and stage, plus the
    two S3 keys the caller needs to fetch. The caller can fetch the
    full public view via GET /signatures/{sign_id}.
    """
    if not row.callback_url:
        return

    body = {
        "sign_id": row.sign_id,
        "stage": row.stage,
        "hash_signed": row.hash_signed,
        "signed_at": row.signed_at.isoformat() if row.signed_at else None,
        "cert_serial": row.cert_serial,
    }
    try:
        resp = requests.post(
            row.callback_url,
            json=body,
            timeout=_CALLBACK_TIMEOUT_S,
        )
    except requests.RequestException as e:
        Logger.log("ERROR", f"sign: callback error for {row.sign_id[:6]}: {e}")
        row.record_callback(sent=False, error=f"http_error: {e}")
        return

    if 200 <= resp.status_code < 300:
        row.record_callback(sent=True)
    else:
        Logger.log(
            "ERROR",
            f"sign: callback for {row.sign_id[:6]} returned {resp.status_code}",
        )
        row.record_callback(
            sent=False, error=f"http_status_{resp.status_code}"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def handler(event, context):
    """Async Lambda entry. `event` is the raw payload from invoke_async
    (see verify_otp): `{"sign_id": "..."}`. Returns a minimal dict for
    CloudWatch clarity; nothing else observes it.
    """
    sign_id = (event or {}).get("sign_id")
    if not sign_id or not isinstance(sign_id, str):
        Logger.log("ERROR", "sign: missing or invalid sign_id in payload")
        return {"ok": False, "error": "missing_sign_id"}

    row = Signatures.get_by_sign_id(sign_id)
    if row is None:
        Logger.log("ERROR", f"sign: no row for sign_id={sign_id[:6]}")
        return {"ok": False, "error": "signature_not_found"}

    # Idempotence: verify_otp promises stage=='signing', but a manual
    # retry via `aws lambda invoke` could arrive here on a row that's
    # already signed or failed. Skip in either case.
    if row.stage in ("signed", "failed", "expired"):
        Logger.log(
            "INFO",
            f"sign: sign_id={sign_id[:6]} already terminal (stage={row.stage}); skipping",
        )
        return {"ok": True, "skipped": True, "stage": row.stage}

    if row.stage != "signing":
        Logger.log(
            "ERROR",
            f"sign: sign_id={sign_id[:6]} at stage={row.stage}, expected 'signing'",
        )
        return {"ok": False, "error": "bad_stage", "stage": row.stage}

    try:
        _run_pipeline(row)
        db_session.commit()
        Logger.log(
            "INFO",
            f"sign: sign_id={sign_id[:6]} completed cert={row.cert_serial}",
        )
        return {
            "ok": True,
            "sign_id": row.sign_id,
            "hash_signed": row.hash_signed,
            "cert_serial": row.cert_serial,
        }
    except SigningError as e:
        Logger.log(
            "ERROR",
            f"sign: sign_id={sign_id[:6]} failed with {e.code}: {e.detail}",
        )
        # Recover the row from the failed transaction so mark_failed can flush.
        db_session.rollback()
        row = Signatures.get_by_sign_id(sign_id)
        if row is not None:
            row.mark_failed(e.code)
            db_session.commit()
        return {"ok": False, "error": e.code}
    except Exception as e:
        Logger.log("ERROR", f"sign: sign_id={sign_id[:6]} crashed: {e}")
        db_session.rollback()
        row = Signatures.get_by_sign_id(sign_id)
        if row is not None:
            row.mark_failed("internal_error")
            db_session.commit()
        return {"ok": False, "error": "internal_error"}
    finally:
        db_session.close()


# ---------------------------------------------------------------------------
# The pipeline itself
# ---------------------------------------------------------------------------
def _run_pipeline(row: Signatures) -> None:
    # (1) Confirm the drawn signature is present -- upload_url +
    # register_signature ran BEFORE consent/OTP, so this should be True.
    if not row.signature_key:
        raise SigningError("missing_signature_key")

    original_key = f"transactions/{row.sign_id}/original.pdf"

    # (2) Download inputs.
    pdf_bytes = _get_object(original_key)
    drawing_bytes = _get_object(row.signature_key)

    # (3) Integrity check on the source PDF. `create` stored the
    # sha256 at ceremony creation; a mismatch here means someone
    # tampered with the object in S3 (or `create` itself was called
    # with a lying URL). Fail cleanly rather than sign a swapped
    # document.
    actual_original_hash = _sha256(pdf_bytes)
    if actual_original_hash != row.hash_original:
        raise SigningError(
            "original_pdf_tampered",
            f"expected {row.hash_original}, got {actual_original_hash}",
        )

    # (4) Issue leaf cert. Private key stays in this function's
    # local scope for the rest of the invocation and dies with it.
    try:
        cert_pem, private_key_pem, serial_hex = issue_transaction_cert(
            sign_id=row.sign_id,
            signer_email=row.signer_email,
            signer_name=row.signer_name,
        )
    except Exception as e:
        raise SigningError("cert_issuance_failed", str(e)) from e

    # (5) Stamp the drawing at the signer's chosen location.
    try:
        stamped_pdf = stamp_drawing_on_pdf(
            pdf_bytes=pdf_bytes,
            drawing_png=drawing_bytes,
            signature_location=row.signature_location,
        )
    except Exception as e:
        raise SigningError("stamp_failed", str(e)) from e

    # (6) PAdES-B sign. Signature widget is INVISIBLE (signature_location
    # =None) because the signer's drawn autograph was already stamped
    # onto the page in step 5 -- that IS the visual affordance. A
    # visible pyhanko widget would either (a) overlap the drawing with
    # its default "Digitally signed by X" text or (b) explode with
    # `Fraction(0, 0)` if we tried to shrink it to a corner (pyhanko's
    # appearance renderer can't cope with degenerate boxes).
    # Adobe Reader / pdfsig / etc. still show the signature panel and
    # can verify the PAdES chain -- visibility is orthogonal to signing.
    try:
        signed_pdf = sign_pdf_pades_b(
            pdf_bytes=stamped_pdf,
            cert_pem=cert_pem,
            private_key_pem=private_key_pem,
            signature_location=None,
        )
    except Exception as e:
        raise SigningError("pades_signing_failed", str(e)) from e

    # (7) Hash the signed output (this hash is what /verify recomputes).
    hash_signed = _sha256(signed_pdf)

    # (8) Upload signed PDF. Lives under evidence-archive/, not
    # transactions/ -- see module docstring.
    signed_key = f"evidence-archive/{row.sign_id}/signed.pdf"
    _put_object(signed_key, signed_pdf, "application/pdf")

    # (9) Mark the row signed BEFORE building the evidence package, so
    # `build_evidence_package` reads a row with the final columns
    # populated. `mark_signed` flushes but does not commit -- the
    # top-level `db_session.commit()` handles that.
    now = datetime.now(timezone.utc)
    row.mark_signed(
        hash_signed=hash_signed,
        cert_serial=serial_hex,
        signed_at=now,
    )

    # (10) Build the evidence package and upload it.
    package = build_evidence_package(
        signature=row,
        signed_pdf_key=signed_key,
        original_pdf_key=original_key,
        cert_pem=cert_pem.decode("utf-8"),
    )
    package_bytes = json.dumps(package, indent=2, default=str).encode("utf-8")
    package_key = f"evidence-archive/{row.sign_id}/evidence-package.json"
    _put_object(package_key, package_bytes, "application/json")

    # Commit BEFORE firing the callback. Rationale: the callback lambda
    # (processes/signature_callback) implements a "zero-trust" model
    # where it re-reads the ceremony state from the database rather
    # than trusting the payload. If we haven't committed yet, that read
    # runs against its own separate DB session and sees the OLD row
    # (stage='signing') because our transaction is still open. The
    # callback then logs "unexpected stage=signing" and skips advancing
    # the process -- silently breaking the frontend push-notification
    # flow (polling still recovers, so this is easy to miss).
    #
    # Committing here means:
    #   * The signed.pdf / evidence-package.json S3 puts already
    #     happened (idempotent PUTs, safe to reissue if we later fail).
    #   * The row's stage='signed' + hash_signed + cert_serial are
    #     durable before we let anyone else observe the row.
    #   * The outer commit in `handler()` becomes a no-op (nothing
    #     dirty), which is fine.
    db_session.commit()

    # (11) Fire the callback (best effort; never raises).
    _fire_callback(row)
    # Commit again to flush `record_callback` bookkeeping (sent flag,
    # error string). Failure here is not fatal -- the ceremony IS
    # signed by this point, and the callback outcome is only used for
    # support diagnostics.
    db_session.commit()
