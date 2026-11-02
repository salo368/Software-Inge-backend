"""Issues a fresh OTP and emails it to the signer.

Flow:

    1. Load ceremony (require_sign_id).
    2. Stage guard: only 'consent' or 'otp' are allowed. The latter
       covers the "resend the code" button on the microfront -- the
       ORM's `issue_otp()` regenerates the hash and resets the attempt
       counter, so a resend implicitly invalidates the previous code.
    3. Call `row.issue_otp()` which returns the plaintext 6-digit code
       and stamps the hash + expires_at + stage='otp' on the row.
    4. Render the email via `utils.otp_email` and send it via
       `libs.core.mailer.send_email`.
    5. The response NEVER echoes the plaintext OTP UNLESS the caller
       proves knowledge of the SSM-provisioned debug key by
       HMAC-signing this ceremony's sign_id (see
       `_authorized_for_debug_otp`). That branch is only reachable in
       dev, where the SSM param is provisioned by
       `scripts/bootstrap-signatures-v2.sh`; production never sets it
       and never exposes the plaintext.

Non-blocking email delivery: `send_email` returns False if SMTP is
misconfigured or the send failed. In that case we still return 200 so
the signer doesn't retry and burn a new OTP; the ORM row already has
the fresh hash and the operator can look up the code via CloudWatch
(the OTP is logged at DEBUG only, never at INFO or above). This is
the same trade-off the rest of the codebase makes for transactional
email.

Failure modes:

    * stage_not_allowed_current_*  -> 409/410

Notes on OTP secrecy:

    * `row.issue_otp()` returns the plaintext once. We hand it to the
      email renderer and to nothing else.
    * The row stores only the SHA-256 hash of the OTP; nobody with
      DB access can read the plaintext.
    * `Logger.log("INFO", ...)` calls in this file never mention the
      plaintext.
    * Debug disclosure (see below) logs the *decision* to disclose,
      not the OTP value.

Debug OTP escape hatch (dev-only, integration tests):

    Automated integration tests need to complete a full ceremony
    end-to-end, which requires knowing the plaintext OTP. Rather than
    (a) parsing emails via IMAP, (b) storing the plaintext in the DB,
    or (c) opening a `_debug/get-otp` endpoint, we expose the OTP in
    the same `POST /signatures/{sign_id}/otp` response body under the
    key `_debug_otp` when TWO conditions hold:

      1. The SSM parameter `${SSM_DEBUG_OTP_KEY_PATH}` exists AND is
         readable by this lambda. In production the param is not
         provisioned, so `_load_debug_otp_key` returns None and the
         branch is dead code.
      2. The caller presents the header `X-Debug-OTP-Signature` whose
         value is `hex(hmac_sha256(debug_key, sign_id))`. The HMAC is
         bound to sign_id so that stealing the header from one request
         cannot be replayed to disclose another ceremony's OTP.

    Constant-time comparison. Underscore-prefixed response key marks
    it as unstable / not part of the public contract.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional

import boto3

from libs.core.logger import Logger
from libs.core.mailer import send_email
from libs.core.responses import generate_response, handle_exceptions

from utils.auth import ensure_stage_allows, require_sign_id
from utils.otp_email import render_otp_email


_ALLOWED_STAGES = ("consent", "otp")

# SSM path holding the debug OTP HMAC key. Value is a raw string
# (typically 64 hex chars); read as bytes for hmac.new(). Missing env
# var OR missing SSM param OR unreadable SSM param all collapse to
# "feature disabled" -- `_load_debug_otp_key` returns None.
SSM_DEBUG_OTP_KEY_PATH = os.environ.get("SSM_DEBUG_OTP_KEY_PATH")

# Cache the debug key across warm invocations so a legitimate CI run
# doesn't hammer SSM. `None` is a valid cached value meaning "feature
# disabled here"; `_debug_key_loaded` distinguishes cold state.
_debug_key: Optional[bytes] = None
_debug_key_loaded = False


def _load_debug_otp_key() -> Optional[bytes]:
    """Returns the debug HMAC key, or None if the feature is disabled.

    Any read failure (missing env var, missing SSM param, IAM denied,
    network hiccup) yields None. That is the safe default: `feature
    disabled` never accidentally leaks the plaintext OTP.
    """
    global _debug_key, _debug_key_loaded
    if _debug_key_loaded:
        return _debug_key
    _debug_key_loaded = True
    if not SSM_DEBUG_OTP_KEY_PATH:
        return None
    try:
        resp = boto3.client("ssm").get_parameter(
            Name=SSM_DEBUG_OTP_KEY_PATH, WithDecryption=True
        )
        value = resp["Parameter"]["Value"].strip()
        if not value:
            return None
        _debug_key = value.encode()
    except Exception as e:
        # Log at WARNING (not ERROR) because this is expected in stages
        # where the param was not provisioned. The one-time cache miss
        # penalty is fine.
        Logger.log(
            "WARNING",
            f"request_otp: debug OTP key unavailable at "
            f"{SSM_DEBUG_OTP_KEY_PATH} ({type(e).__name__})",
        )
        _debug_key = None
    return _debug_key


def _authorized_for_debug_otp(headers: Optional[dict], sign_id: str) -> bool:
    """True iff the caller proves knowledge of the debug key.

    Expected header (case-insensitive because API Gateway lowercases):

        X-Debug-OTP-Signature: <hex(hmac_sha256(debug_key, sign_id))>

    Binding the HMAC to sign_id (rather than a static value) means
    intercepting the header for ceremony A cannot be replayed against
    ceremony B. Comparison is constant-time.
    """
    debug_key = _load_debug_otp_key()
    if not debug_key or not sign_id:
        return False
    provided: Optional[str] = None
    for k, v in (headers or {}).items():
        if k and k.lower() == "x-debug-otp-signature":
            provided = v
            break
    if not provided or not isinstance(provided, str):
        return False
    expected = hmac.new(
        debug_key, sign_id.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, provided)


@handle_exceptions
@require_sign_id
def handler(event, context):
    row = event["signature"]
    ensure_stage_allows(row, _ALLOWED_STAGES)

    plaintext_otp = row.issue_otp()  # advances stage to 'otp'

    subject, html = render_otp_email(
        otp=plaintext_otp,
        signer_name=row.signer_name,
        expires_at=row.otp_expires_at,
        sign_id=row.sign_id,
    )
    sent = send_email(row.signer_email, subject, html)
    if not sent:
        # Operator can pull the plaintext from CloudWatch DEBUG logs if
        # this ever fires in dev; in production, an alert should page
        # someone (out of scope for this repo).
        Logger.log(
            "ERROR",
            f"request_otp: mailer refused OTP for sign_id={row.sign_id[:6]}"
            " (SMTP misconfigured?)",
        )

    body: dict = {
        "sign_id": row.sign_id,
        "stage": row.stage,
        "signer_email_masked": row.masked_email,
        "otp": {
            "expires_at": row.otp_expires_at.isoformat(),
            # `attempts_left` uses the ORM's public formula so it
            # stays in sync with MAX_OTP_ATTEMPTS if we ever tune it.
            "attempts_left": row.public_dict()["otp"]["attempts_left"],
            "email_sent": sent,
        },
    }

    # Debug OTP escape hatch. Only reachable when the SSM key is
    # provisioned AND the caller HMAC-signed sign_id with it. Never
    # log the plaintext -- only the decision to disclose it, so a
    # replay of the log won't reveal past OTPs.
    if _authorized_for_debug_otp(event.get("headers"), row.sign_id):
        body["_debug_otp"] = plaintext_otp
        Logger.log(
            "INFO",
            f"request_otp: sign_id={row.sign_id[:6]} disclosed OTP to "
            f"authenticated debug caller",
        )

    return generate_response(body)
