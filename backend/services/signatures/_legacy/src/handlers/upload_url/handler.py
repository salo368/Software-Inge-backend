"""Issues a presigned PUT URL so the signer's browser uploads an evidence
file directly to signatures' own S3 bucket.

Four evidence types are accepted, each with a fixed key under
`transactions/{sign_id}/` and a whitelist of content-types:

  * id_front           identity document, front  (image/jpeg, image/png)
  * id_back            identity document, back   (image/jpeg, image/png)
  * face               selfie                    (image/jpeg, image/png)
  * signature_drawing  drawn autograph, canvas   (image/png)

Rationale for direct-to-S3 uploads (instead of streaming through the
lambda):
  * ID and selfie files are 1-5 MB; API Gateway caps at 6 MB per
    request and Lambda invocation payloads at 6 MB, so a two-step
    presign + PUT is cheaper and more reliable.
  * The lambda never touches the bytes; validation runs afterwards by
    other lambdas (`validate_id_front`, etc.) that read from S3.

Terminal stages reject uploads. Consented / mid-flow stages allow
re-uploading (a bad selfie can be retried without restarting the whole
ceremony).

Presign TTL is 5 minutes so a leaked URL is short-lived. The microfront
requests a fresh URL immediately before each upload attempt.
"""

from __future__ import annotations

import json
import os

import boto3
from botocore.config import Config

from libs.core.responses import HandledError, generate_response, handle_exceptions

from utils.auth import ensure_stage_allows, require_sign_id


SIGNATURES_BUCKET = os.environ["SIGNATURES_BUCKET"]
_PRESIGN_TTL_SECONDS = 60 * 5


# evidence_type -> (S3 key prefix under transactions/{sign_id}/,
#                   allowed content-types).
_EVIDENCE_MAP = {
    "id_front":          ("id/front",  {"image/jpeg", "image/png"}),
    "id_back":           ("id/back",   {"image/jpeg", "image/png"}),
    "face":              ("face",      {"image/jpeg", "image/png"}),
    "signature_drawing": ("signature", {"image/png"}),
}

_EXT_FROM_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/png":  "png",
}

# Stages that allow evidence uploads. Terminal stages (signed, expired,
# failed) are caught earlier by `ensure_stage_allows`; anything not
# listed here means "you're past the evidence phase, stop uploading".
# The stages the ORM actually models -- see STAGES in libs/orm/signatures.py.
# Terminal states are caught earlier by `ensure_stage_allows`; `otp` and
# `signing` are excluded so re-uploading cannot silently invalidate an
# already-issued challenge.
_ALLOWED_STAGES = ("created", "identity", "consent")


@handle_exceptions
@require_sign_id
def handler(event, context):
    row = event["signature"]
    ensure_stage_allows(row, _ALLOWED_STAGES)

    body = json.loads(event.get("body") or "{}")
    evidence_type = body.get("evidence_type")
    content_type = body.get("content_type", "image/jpeg")

    mapping = _EVIDENCE_MAP.get(evidence_type)
    if mapping is None:
        raise HandledError("invalid_evidence_type", 400)
    prefix, allowed_types = mapping
    if content_type not in allowed_types:
        raise HandledError("invalid_content_type", 400)

    ext = _EXT_FROM_CONTENT_TYPE[content_type]
    key = f"transactions/{row.sign_id}/{prefix}.{ext}"

    s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": SIGNATURES_BUCKET,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=_PRESIGN_TTL_SECONDS,
    )

    return generate_response(
        {
            "upload_url": upload_url,
            "key": key,
            "expires_in": _PRESIGN_TTL_SECONDS,
        }
    )
