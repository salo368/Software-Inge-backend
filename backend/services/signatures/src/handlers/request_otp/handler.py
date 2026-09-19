"""Issues the one-time code that seals the ceremony.

Requires the drawn signature to already be on file, so the code is only ever
in flight for a ceremony that is one step from done.
"""
import os

from libs.core.mailer import send_email
from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.signatures import Signatures
from utils.emails import otp_html

STAGE = os.environ.get("STAGE", "dev")


@handle_exceptions
def handler(event, context):
    token = (event.get("pathParameters") or {}).get("token", "")
    row = Signatures.get_by_token(token)
    if row is None:
        raise HandledError("signature_not_found", 404)
    if row.stage == "signed":
        raise HandledError("already_signed", 409)
    if not row.signature_key:
        raise HandledError("signature_missing", 409)

    otp = row.issue_otp()
    delivered = send_email(row.email, "Tu código de firma · CDTs", otp_html(otp))

    payload = {"status": "sent" if delivered else "undelivered", "stage": row.stage}
    if not delivered and STAGE != "pro":
        # Outside production a missing mailbox must not block the flow; the
        # code is surfaced so dev and QA can finish the ceremony.
        payload["dev_otp"] = otp
    return generate_response(payload)
