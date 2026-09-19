"""Hands out a presigned PUT for one piece of identity evidence.

The key is recorded right away so a refresh mid-ceremony resumes where the
signer left off. Evidence lives under `signatures/` rather than `processes/`
so it does not trip the files service upload trigger.
"""
import json
import os

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.core.s3 import presign_upload
from libs.orm.signatures import EVIDENCE_TYPES, Signatures

BUCKET = os.environ["FILES_BUCKET"]
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png"}


@handle_exceptions
def handler(event, context):
    token = (event.get("pathParameters") or {}).get("token", "")
    row = Signatures.get_by_token(token)
    if row is None:
        raise HandledError("signature_not_found", 404)
    if row.stage == "signed":
        raise HandledError("already_signed", 409)

    body = json.loads(event.get("body") or "{}")
    evidence_type = body.get("type")
    content_type = body.get("content_type", "image/jpeg")
    if evidence_type not in EVIDENCE_TYPES:
        raise HandledError(f"type must be one of {sorted(EVIDENCE_TYPES)}", 400)
    if content_type not in EXTENSIONS:
        raise HandledError("content_type must be image/jpeg or image/png", 400)

    key = f"signatures/{token}/{evidence_type}.{EXTENSIONS[content_type]}"
    url = presign_upload(BUCKET, key, content_type)
    row.attach_evidence(evidence_type, key)

    return generate_response({
        "upload_url": url,
        "key": key,
        "upload_headers": {"Content-Type": content_type},
        "stage": row.stage,
    })
