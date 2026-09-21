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
    5. The response NEVER echoes the plaintext OTP. It reports the
       masked email, the expires_at timestamp, and the remaining
       attempts (always MAX_OTP_ATTEMPTS at issue time).

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
"""

from __future__ import annotations

from libs.core.logger import Logger
from libs.core.mailer import send_email
from libs.core.responses import generate_response, handle_exceptions

from utils.auth import ensure_stage_allows, require_sign_id
from utils.otp_email import render_otp_email


_ALLOWED_STAGES = ("consent", "otp")


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

    return generate_response(
        {
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
    )
