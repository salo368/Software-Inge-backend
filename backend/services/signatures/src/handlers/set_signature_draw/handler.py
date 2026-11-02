import base64
import os
from datetime import datetime, timezone
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.core.s3 import upload_from_bytes
from libs.orm.signatures import SIGNING_WINDOW, SignatureStage, Signatures

BUCKET = os.environ["SIGNATURES_BUCKET"]

# Format-agnostic (PNG vs SVG isn't decided yet): a blank canvas exported
# by a browser is a few hundred bytes, a real signature image is bigger.
# These bounds just reject an empty upload and an unreasonably large one.
_MIN_BYTES = 100
_MAX_BYTES = 2 * 1024 * 1024


@handle_exceptions
def handler(event, context):

    query_params = event.get("queryStringParameters") or {}

    signature_id_raw = query_params.get("signature_id")
    if not signature_id_raw:
        raise HandledError("signature_id is required", 400)
    try:
        signature_id = UUID(signature_id_raw)
    except (TypeError, ValueError):
        raise HandledError("invalid signature_id", 400)

    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        file_bytes = base64.b64decode(body)
    else:
        file_bytes = body.encode("utf-8") if isinstance(body, str) else body

    if len(file_bytes) < _MIN_BYTES:
        raise HandledError("draw_invalid_empty", 422)
    if len(file_bytes) > _MAX_BYTES:
        raise HandledError("draw_invalid_too_large", 413)

    row = Signatures.get_by_id(signature_id)
    if row is None:
        raise HandledError("signature_not_found", 404)

    if datetime.now(timezone.utc) > row.created_at + SIGNING_WINDOW:
        raise HandledError("signature_expired", 410)

    if row.stage != SignatureStage.SIGNATURE.value:
        raise HandledError("signature_not_in_signature_stage", 409)

    draw_s3_key = f"signatures/{signature_id}/draw.bin"

    upload_from_bytes(BUCKET, draw_s3_key, file_bytes, content_type="application/octet-stream")

    updated = Signatures.set_draw_key(signature_id, draw_s3_key)

    response = {
        "id": updated.id,
        "stage": updated.stage,
        "draw_s3_key": updated.draw_s3_key,
    }

    return generate_response(response, 200)
