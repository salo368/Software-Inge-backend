"""Returns the full state of a signature ceremony to the microfront.

Public in the sense that anyone with the `sign_id` can call it. The
`sign_id` is a 32-byte urlsafe token (~256 bits of entropy), so it is
the credential -- there is no additional auth on top. This mirrors how
DocuSign-style "signing links" work: possession of the link IS the
authorization to operate that specific ceremony.

Response = `Signatures.public_dict()` plus two handler-only additions:

  * `signer_name`        the display name the caller passed to `create`.
                         Not in `public_dict()` because processes.get
                         doesn't need it in the embedded ceremony blob.
  * `pdf_url`            fresh presigned GET URL to the ORIGINAL PDF
                         (15-min TTL, microfront refreshes on reload).
  * `signed_pdf_url`     fresh presigned GET URL to the SIGNED PDF.
                         Only included when `stage == 'signed'`; earlier
                         stages don't have the object yet.

Everything else (masked email, uploads_state, consent, otp, hashes,
cert_serial, timestamps) is inherited from `public_dict()`.

Deliberately NOT returned: `callback_url`, `service_caller`. Those are
internal-only fields; the signer has no business seeing them.

Deliberately IS returned (previously hidden): `hash_original`,
`hash_signed`, `cert_serial`. These are safe to disclose to the signer:

  * hash_original -- the signer already has the PDF via `pdf_url`, they
    can recompute the SHA-256 themselves. Exposing it lets the front-end
    display "you are signing document with fingerprint abc123" for
    transparency.
  * hash_signed / cert_serial -- once signed, both are embedded in the
    PDF byte-range and readable by any PDF viewer. Nothing to hide.
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


def _presign_get(s3, key: str) -> str:
    """Small helper to keep the three presign calls DRY."""
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": SIGNATURES_BUCKET, "Key": key},
        ExpiresIn=_PRESIGN_TTL_SECONDS,
    )


@handle_exceptions
@require_sign_id
def handler(event, context):
    row = event["signature"]

    s3 = boto3.client("s3", config=Config(signature_version="s3v4"))

    payload = row.public_dict()
    # signer_name is not in public_dict() to keep processes.get lean;
    # the signing SPA wants it to greet the signer ("Hola, Juan").
    payload["signer_name"] = row.signer_name
    payload["pdf_url"] = _presign_get(
        s3, f"transactions/{row.sign_id}/original.pdf"
    )

    # signed.pdf only exists once the async sign worker completes and
    # transitions the row to 'signed'. Presigning before then would 403
    # anyone who followed the URL, so only expose it in the terminal
    # state.
    if row.stage == "signed":
        payload["signed_pdf_url"] = _presign_get(
            s3, f"transactions/{row.sign_id}/signed.pdf"
        )

    return generate_response(payload)
