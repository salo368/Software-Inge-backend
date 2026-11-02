import json
import os
from datetime import datetime, timezone
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.core.s3 import presign_upload
from libs.orm.signatures import SIGNING_WINDOW, BiometricType, SignatureStage, Signatures

BUCKET = os.environ["SIGNATURES_BUCKET"]

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}
_EXTENSION_BY_CONTENT_TYPE = {"image/jpeg": "jpg", "image/png": "png"}

_PREFIX_BY_TYPE = {
    BiometricType.ID_FRONT.value: "id_front",
    BiometricType.ID_BACK.value: "id_back",
    BiometricType.FACE.value: "face",
}


@handle_exceptions
def handler(event, context):

    body = json.loads(event.get("body") or "{}")

    signature_id_raw = body.get("signature_id")
    if not signature_id_raw:
        raise HandledError("signature_id is required", 400)
    try:
        signature_id = UUID(signature_id_raw)
    except (TypeError, ValueError):
        raise HandledError("invalid signature_id", 400)

    biometric_type = body.get("biometric_type")
    if biometric_type not in _PREFIX_BY_TYPE:
        raise HandledError(f"biometric_type must be one of {sorted(_PREFIX_BY_TYPE)}", 400)

    content_type = body.get("content_type", "image/jpeg")
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HandledError(f"content_type must be one of {sorted(ALLOWED_CONTENT_TYPES)}", 400)

    row = Signatures.get_by_id(signature_id)
    if row is None:
        raise HandledError("signature_not_found", 404)

    if datetime.now(timezone.utc) > row.created_at + SIGNING_WINDOW:
        raise HandledError("signature_expired", 410)

    if row.stage != SignatureStage.BIOMETRICS.value:
        raise HandledError("signature_not_in_biometrics_stage", 409)

    ext = _EXTENSION_BY_CONTENT_TYPE[content_type]
    key = f"signatures/{signature_id}/{_PREFIX_BY_TYPE[biometric_type]}.{ext}"

    upload_url = presign_upload(BUCKET, key, content_type)

    response = {
        "upload_url": upload_url,
        "key": key,
        "content_type": content_type,
        "expires_in": 900,
    }

    return generate_response(response, 200)
