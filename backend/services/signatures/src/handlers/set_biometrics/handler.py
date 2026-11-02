import json
import os
from datetime import datetime, timezone
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.signatures import SIGNING_WINDOW, SignatureStage, Signatures
from libs.utils.biometrics import analyze_face, analyze_id_back, analyze_id_front

BUCKET = os.environ["SIGNATURES_BUCKET"]

_ANALYZERS = {
    "ID_FRONT": analyze_id_front,
    "ID_BACK": analyze_id_back,
    "FACE": analyze_face,
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
    if biometric_type not in _ANALYZERS:
        raise HandledError(f"biometric_type must be one of {sorted(_ANALYZERS)}", 400)

    s3_key = body.get("s3_key")
    if not s3_key:
        raise HandledError("s3_key is required", 400)
    if not s3_key.startswith(f"signatures/{signature_id}/"):
        raise HandledError("s3_key does not belong to this signature", 400)

    row = Signatures.get_by_id(signature_id)
    if row is None:
        raise HandledError("signature_not_found", 404)

    if datetime.now(timezone.utc) > row.created_at + SIGNING_WINDOW:
        raise HandledError("signature_expired", 410)

    if row.stage != SignatureStage.BIOMETRICS.value:
        raise HandledError("signature_not_in_biometrics_stage", 409)

    is_valid, reason = _ANALYZERS[biometric_type](BUCKET, s3_key)

    if is_valid:
        Signatures.set_biometric_key(signature_id, biometric_type, s3_key)

    response = {"is_valid": is_valid, "reason": reason}

    return generate_response(response, 200)
