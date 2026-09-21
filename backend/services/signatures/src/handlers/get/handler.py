"""Returns the full state of a signature ceremony to the microfront.

Public in the sense that anyone with the `sign_id` can call it. The
`sign_id` is a 32-byte urlsafe token (~256 bits of entropy), so it is
the credential -- there is no additional auth on top. This mirrors how
DocuSign-style "signing links" work: possession of the link IS the
authorization to operate that specific ceremony.

Response payload is what the microfront needs to render the ceremony:
  * `stage`               where we are in the lifecycle (see ORM)
  * `signer_email`        so the microfront can show it (already known
                          to the signer, no leak)
  * `signature_location`  {page, x_pct, y_pct, ...} for the drawing box
  * `pdf_url`             fresh presigned GET URL to the original PDF
                          (15-min TTL, microfront refreshes on reload)
  * `expires_at`          hard TTL of the ceremony (CEREMONY_TTL)

We deliberately do NOT return the callback_url, service_caller, cert
serial, or any evidence-key/hash fields: those belong to the audit
package, not to the signer's UX.
"""

from __future__ import annotations

import os

import boto3
from botocore.config import Config

from libs.core.responses import generate_response, handle_exceptions

from utils.auth import require_sign_id


SIGNATURES_BUCKET = os.environ["SIGNATURES_BUCKET"]
# The microfront refreshes on page reload, so a short TTL is fine and
# prevents a leaked URL from surviving beyond a single browsing session.
_PRESIGN_TTL_SECONDS = 60 * 15


@handle_exceptions
@require_sign_id
def handler(event, context):
    row = event["signature"]

    s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
    pdf_url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": SIGNATURES_BUCKET,
            "Key": f"transactions/{row.sign_id}/original.pdf",
        },
        ExpiresIn=_PRESIGN_TTL_SECONDS,
    )

    return generate_response(
        {
            "sign_id": row.sign_id,
            "stage": row.stage,
            "signer_email": row.signer_email,
            "signer_name": row.signer_name,
            "signature_location": row.signature_location,
            "pdf_url": pdf_url,
            "expires_at": row.expires_at.isoformat(),
            "created_at": row.created_at.isoformat(),
        }
    )
