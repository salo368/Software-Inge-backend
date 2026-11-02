from datetime import datetime, timezone
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.signatures import BIOMETRIC_COLUMNS, SIGNING_WINDOW, SignatureStage, Signatures


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

    row = Signatures.get_by_id(signature_id)
    if row is None:
        raise HandledError("signature_not_found", 404)

    if datetime.now(timezone.utc) > row.created_at + SIGNING_WINDOW:
        raise HandledError("signature_expired", 410)

    status = {
        biometric_type: getattr(row, column) is not None
        for biometric_type, column in BIOMETRIC_COLUMNS.items()
    }

    if row.stage == SignatureStage.BIOMETRICS.value and all(status.values()):
        Signatures.advance_to_signature_stage(signature_id)

    return generate_response(status, 200)
