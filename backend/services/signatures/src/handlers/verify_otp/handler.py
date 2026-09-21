"""Verifies the OTP the signer received by email.

Success path:

    1. Load ceremony and gate on stage=='otp'.
    2. Body validation: `code` must be a 6-digit string.
    3. Reject expired OTPs (otp_expires_at < now).
    4. Reject if attempts are already exhausted (defensive; the
       previous failure path locks the ceremony by marking it failed).
    5. Constant-time OTP match via `row.otp_matches`; on mismatch,
       decrement attempts_left and return 401 with the remaining
       attempts so the microfront can show "3 tries left".
    6. On match, call `row.start_signing()` which advances the row to
       stage='signing' and clears the OTP hash (single-use).
    7. Invoke the internal `sign` Lambda asynchronously. This Lambda
       exists starting fase 4e; before that a feature flag
       (`SIGN_LAMBDA_READY`) leaves the invoke as a WARNING log so a
       Fase 4d dev deploy still returns 200 from this handler even
       though the ceremony stays at 'signing' forever. Once Fase 4e
       sets the flag to 'true' in the block's env, the invoke fires
       and the sign Lambda drives the ceremony to 'signed'/'failed'.

The plaintext OTP is never returned in a response and never logged
at INFO or higher.

Failure modes:

    * missing_code                -> 400
    * invalid_code_format         -> 400
    * otp_expired                 -> 401
    * otp_invalid                 -> 401 (with attempts_left)
    * otp_max_attempts            -> 429 (ceremony marked failed)
    * stage_not_allowed_current_* -> 409/410
    * sign_lambda_unavailable     -> 502 (only when SIGN_LAMBDA_READY
                                    is 'true' and the async invoke
                                    submission was rejected by AWS)
"""

from __future__ import annotations

import json
import os
import re

from libs.core.logger import Logger
from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.utils.lambda_invoke import (
    LambdaInvokeError,
    invoke_async,
    resolve_function_name,
)

from utils.auth import ensure_stage_allows, require_sign_id


# Six digits, matches the ORM's `issue_otp` format ("%06d").
_CODE_RE = re.compile(r"^\d{6}$")

_ALLOWED_STAGES = ("otp",)

# Feature flag: True enables the async invoke of the internal `sign`
# Lambda. Left False (default) in fase 4d so the deploy pipeline can
# ship this handler before the sign Lambda exists (see fase 4e). Once
# fase 4e lands, set SIGN_LAMBDA_READY=true in the block's env.
SIGN_LAMBDA_READY = os.environ.get("SIGN_LAMBDA_READY", "").strip().lower() == "true"


def _utcnow():
    # Imported inside so tests can monkeypatch it if they need to move
    # time forward without touching the whole datetime module.
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


@handle_exceptions
@require_sign_id
def handler(event, context):
    row = event["signature"]
    ensure_stage_allows(row, _ALLOWED_STAGES)

    body = json.loads(event.get("body") or "{}")
    code = body.get("code")
    if not code:
        raise HandledError("missing_code", 400)
    if not isinstance(code, str) or not _CODE_RE.match(code):
        raise HandledError("invalid_code_format", 400)

    if row.otp_expires_at is None or row.otp_expires_at < _utcnow():
        raise HandledError("otp_expired", 401)

    # Guard against pre-locked ceremonies. Under normal conditions the
    # previous failing verify_otp call would have caught this at
    # attempts_left==0 and marked the ceremony failed; this branch
    # catches races and manual DB tampering.
    remaining_before = row.public_dict()["otp"]["attempts_left"]
    if remaining_before <= 0:
        row.mark_failed("otp_max_attempts")
        raise HandledError("otp_max_attempts", 429)

    if not row.otp_matches(code):
        remaining_after = row.register_failed_attempt()
        if remaining_after <= 0:
            row.mark_failed("otp_max_attempts")
            raise HandledError("otp_max_attempts", 429)
        # 401 keeps the same shape the microfront already expects for
        # auth failures; extra field carries how many chances are left.
        Logger.log(
            "WARNING",
            f"verify_otp: bad code for sign_id={row.sign_id[:6]}"
            f" (attempts_left={remaining_after})",
        )
        return generate_response(
            {"error": "otp_invalid", "attempts_left": remaining_after}, 401
        )

    # OTP matches. Advance stage and clear the hash before we invoke
    # sign, so a retry of this endpoint cannot spawn a second sign job.
    row.start_signing()

    if SIGN_LAMBDA_READY:
        try:
            invoke_async(
                resolve_function_name("signatures", "sign"),
                {"sign_id": row.sign_id},
            )
        except LambdaInvokeError as e:
            # AWS rejected the submission (throttled, sign Lambda not
            # deployed, IAM issue). The row is already at 'signing';
            # returning 502 lets the client show a "try again later"
            # message. An operator can retry via a manual invoke.
            Logger.log(
                "ERROR",
                f"verify_otp: sign invocation failed for sign_id={row.sign_id[:6]}: {e}",
            )
            raise HandledError("sign_lambda_unavailable", 502)
    else:
        Logger.log(
            "WARNING",
            f"verify_otp: SIGN_LAMBDA_READY is off; sign_id={row.sign_id[:6]}"
            " will stay at 'signing' until fase 4e",
        )

    return generate_response(
        {
            "sign_id": row.sign_id,
            "stage": row.stage,
        }
    )
