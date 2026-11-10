import hashlib
import json
import os
import re
from datetime import datetime, timezone
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.core.sqs import send_message
from libs.orm.signatures import (
    MAX_OTP_TRIES,
    OTP_TTL,
    SIGNING_TIMEOUT,
    SIGNING_WINDOW,
    SignatureStage,
    Signatures,
)
from libs.utils.lambda_invoke import LambdaInvokeError, invoke_async
from libs.utils.signature_notifications import notify_terminal_state

_CODE_RE = re.compile(r"^\d{6}$")

SIGNING_TIMEOUT_QUEUE_URL = os.environ["SIGNING_TIMEOUT_QUEUE_URL"]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _capture_telemetry(event: dict) -> dict:
    """Best-effort request telemetry, captured here because sign_doc runs
    async and detached from the original HTTP request -- this is its only
    chance to see things like the signer's IP for the audit page."""
    headers = event.get("headers") or {}
    http_ctx = (event.get("requestContext") or {}).get("http") or {}
    return {
        "ip": http_ctx.get("sourceIp"),
        "user_agent": headers.get("user-agent") or http_ctx.get("userAgent"),
        "accept_language": headers.get("accept-language"),
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }


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
            notify_terminal_state(signature_id, "FAILED")
            return generate_response({"error": "otp_max_attempts"}, 429)
        
        attempts_left = MAX_OTP_TRIES - updated.otp_tries
        return generate_response({"error": "otp_invalid", "attempts_left": attempts_left}, 401)

    signing_data = _capture_telemetry(event)
    updated = Signatures.start_signing(signature_id, signing_data)

    send_message(
        SIGNING_TIMEOUT_QUEUE_URL,
        json.dumps({"signature_id": str(signature_id)}),
        delay_seconds=int(SIGNING_TIMEOUT.total_seconds()),
    )

    try:
        invoke_async("sign_doc", {"signature_id": str(signature_id)})
    except LambdaInvokeError as e:
        raise HandledError("sign_doc_unavailable", 502) from e

    response = {
        "id": updated.id,
        "stage": updated.stage,
    }

    return generate_response(response, 200)
