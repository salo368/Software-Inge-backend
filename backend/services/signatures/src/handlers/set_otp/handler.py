import hashlib
import json
import secrets
from datetime import datetime, timezone
from uuid import UUID

from libs.core.logger import Logger
from libs.core.mailer import send_email
from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.signatures import OTP_TTL, SIGNING_WINDOW, SignatureStage, Signatures
from libs.utils.otp_email import render_otp_email


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@handle_exceptions
def handler(event, context):

    body = json.loads(event.get("body") or "{}")

    signature_id_raw = body.get("signature_id")
    if not signature_id_raw:
        raise HandledError("signature_id is required", 400)
    try:
        signature_id = UUID(signature_id_raw)
    except (TypeError, ValueError):
        raise HandledError("invalid signature_id", 400)

    row = Signatures.get_by_id(signature_id)
    if row is None:
        raise HandledError("signature_not_found", 404)

    if datetime.now(timezone.utc) > row.created_at + SIGNING_WINDOW:
        raise HandledError("signature_expired", 410)

    if row.stage != SignatureStage.OTP.value:
        raise HandledError("signature_not_in_otp_stage", 409)

    otp = f"{secrets.randbelow(1_000_000):06d}"

    updated = Signatures.set_otp(signature_id, _hash(otp))

    subject, html = render_otp_email(
        otp=otp,
        signatory=updated.signatory,
        issued_at=updated.otp_at,
        ttl=OTP_TTL,
        signature_id=updated.id,
    )
    sent = send_email(updated.email, subject, html)
    if not sent:
        Logger.log("ERROR", f"set_otp: mailer refused OTP for signature_id={str(updated.id)[:8]}")

    response = {
        "id": updated.id,
        "stage": updated.stage,
        "email_sent": sent,
        "expires_at": updated.otp_at + OTP_TTL,
    }

    return generate_response(response, 200)
