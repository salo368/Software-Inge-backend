"""Validates the OTP, stamps the signature and closes the ceremony.

The hash is taken over the stamped document before the certificate is
appended, so it stays verifiable by dropping the last page. Once written the
process moves on to `payment` and the signed PDF is registered as a file.
"""
import hashlib
import json
import os
from datetime import datetime, timezone

from libs.core.db import db_session
from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.core.s3 import download_bytes, presign_download, upload_from_bytes
from libs.orm.files import Files
from libs.orm.processes import Processes
from libs.orm.signatures import EVIDENCE_TYPES, MAX_OTP_ATTEMPTS, Signatures
from utils.sign_document import append_pdf, build_certificate, stamp_signature

BUCKET = os.environ["FILES_BUCKET"]


@handle_exceptions
def handler(event, context):
    token = (event.get("pathParameters") or {}).get("token", "")
    row = Signatures.get_by_token(token)
    if row is None:
        raise HandledError("signature_not_found", 404)
    if row.stage == "signed":
        raise HandledError("already_signed", 409)

    body = json.loads(event.get("body") or "{}")
    otp = str(body.get("otp", "")).strip()

    if not row.otp_hash or row.otp_expires_at is None:
        raise HandledError("otp_not_requested", 409)
    if row.otp_expires_at < datetime.now(timezone.utc):
        raise HandledError("otp_expired", 410)
    if row.otp_attempts >= MAX_OTP_ATTEMPTS:
        raise HandledError("too_many_attempts", 429)
    if not row.otp_matches(otp):
        remaining = row.register_failed_attempt()
        # handle_exceptions rolls back on HandledError, which would give the
        # caller unlimited free guesses. Persist the attempt before raising.
        db_session.commit()
        raise HandledError(f"invalid_otp:{max(remaining, 0)}", 401)

    missing = [t for t in EVIDENCE_TYPES if not getattr(row, f"{t}_key")]
    if missing:
        raise HandledError(f"missing_evidence:{','.join(missing)}", 409)

    proc = Processes.get_by_id(row.process_id)
    if proc is None:
        raise HandledError("process_not_found", 404)

    order_pdf = download_bytes(BUCKET, row.pdf_key)
    images = {t: download_bytes(BUCKET, getattr(row, f"{t}_key")) for t in EVIDENCE_TYPES}

    signed_at = datetime.now(timezone.utc)
    stamped = stamp_signature(
        order_pdf, images["signature"], row.page, float(row.pos_x), float(row.pos_y)
    )
    doc_hash = hashlib.sha256(stamped).hexdigest()

    snapshot = proc.form_snapshot or {}
    certificate = build_certificate(
        signature=row,
        order_number=str(proc.id)[:8].upper(),
        holder_name=snapshot.get("full_name") or row.email,
        images=images,
        doc_hash=doc_hash,
        signed_at=signed_at,
    )
    final_pdf = append_pdf(stamped, certificate)

    signed_key = f"signatures/{token}/signed-investment-order.pdf"
    upload_from_bytes(BUCKET, signed_key, final_pdf, "application/pdf")

    row.mark_signed(signed_pdf_key=signed_key, doc_hash=doc_hash, signed_at=signed_at)
    if Files.get_by_key(signed_key) is None:
        Files.register_from_s3(
            process_id=proc.id,
            file_type="signed_investment_order",
            s3_key=signed_key,
            original_name="orden-de-inversion-firmada.pdf",
            size_bytes=len(final_pdf),
            content_type="application/pdf",
        )
    if proc.stage == "signature":
        proc.advance_to("payment")

    return generate_response({
        "status": "signed",
        "doc_hash": doc_hash,
        "signed_pdf_url": presign_download(BUCKET, signed_key),
        "process_id": str(proc.id),
        "process_stage": proc.stage,
    })
