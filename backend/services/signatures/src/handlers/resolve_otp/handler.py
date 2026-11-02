import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.signatures import MAX_OTP_TRIES, OTP_TTL, SIGNING_WINDOW, SignatureStage, Signatures

_CODE_RE = re.compile(r"^\d{6}$")


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

    code = body.get("code")
    if not code:
        raise HandledError("code is required", 400)
    if not isinstance(code, str) or not _CODE_RE.match(code):
        raise HandledError("invalid_code_format", 400)

    row = Signatures.get_by_id(signature_id)
    if row is None:
        raise HandledError("signature_not_found", 404)

    if datetime.now(timezone.utc) > row.created_at + SIGNING_WINDOW:
        raise HandledError("signature_expired", 410)

    if row.stage != SignatureStage.OTP.value:
        raise HandledError("signature_not_in_otp_stage", 409)

    if row.otp_hash is None or row.otp_at is None:
        raise HandledError("otp_not_requested", 409)

    if datetime.now(timezone.utc) > row.otp_at + OTP_TTL:
        raise HandledError("otp_expired", 401)

    if _hash(code) != row.otp_hash:
        
        updated = Signatures.register_failed_otp_attempt(signature_id)

        if updated.otp_tries >= MAX_OTP_TRIES:
            Signatures.mark_failed(signature_id)
            return generate_response({"error": "otp_max_attempts"}, 429)
        
        attempts_left = MAX_OTP_TRIES - updated.otp_tries
        return generate_response({"error": "otp_invalid", "attempts_left": attempts_left}, 401)

    updated = Signatures.mark_signed(signature_id)

    response = {
        "id": updated.id,
        "stage": updated.stage,
    }

    return generate_response(response, 200)
