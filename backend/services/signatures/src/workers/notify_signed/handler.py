"""Internal worker invoked asynchronously by sign_doc right after it
marks a signature SIGNED. Not exposed over HTTP -- invoke-only via IAM.

Emails the signer a link to download the signed PDF (the full one, with
the evidence page -- this goes to the signer's own inbox, not a public
endpoint, so showing their own ID/selfie back to them is fine).

Best-effort: a mailer failure here must never affect the signature's
state, which is already final (SIGNED) by the time this runs.
"""
import os

from libs.core.logger import Logger
from libs.core.mailer import send_email
from libs.core.s3 import presign_download
from libs.orm.signatures import SignatureStage, Signatures
from libs.utils.signed_email import render_signed_email

BUCKET = os.environ["SIGNATURES_BUCKET"]


def handler(event, context):
    signature_id = (event or {}).get("signature_id")
    if not signature_id:
        Logger.log("ERROR", "notify_signed: missing signature_id in payload")
        return {"ok": False, "error": "missing_signature_id"}

    row = Signatures.get_by_id(signature_id)
    if row is None:
        Logger.log("ERROR", f"notify_signed: no row for signature_id={signature_id}")
        return {"ok": False, "error": "signature_not_found"}

    if row.stage != SignatureStage.SIGNED.value or not row.signed_s3_key:
        Logger.log(
            "WARNING",
            f"notify_signed: signature_id={signature_id} at stage={row.stage}, "
            "expected SIGNED with signed_s3_key; skipping",
        )
        return {"ok": False, "skipped": True, "stage": row.stage}

    if not row.email:
        Logger.log("WARNING", f"notify_signed: signature_id={signature_id} has no email on file")
        return {"ok": False, "error": "no_email"}

    signed_url = presign_download(BUCKET, row.signed_s3_key)
    subject, html = render_signed_email(
        signatory=row.signatory,
        signed_at=row.signed_at,
        signed_url=signed_url,
        signature_id=row.id,
    )
    sent = send_email(row.email, subject, html)
    if not sent:
        Logger.log("ERROR", f"notify_signed: mailer refused send for signature_id={signature_id}")

    return {"ok": sent, "signature_id": str(signature_id)}
