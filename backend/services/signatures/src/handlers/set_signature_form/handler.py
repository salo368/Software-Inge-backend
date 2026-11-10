import json
from datetime import datetime, timezone
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.signatures import SIGNING_WINDOW, SignatureStage, Signatures
from libs.utils.validators import valid_email


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

    email = (body.get("email") or "").strip().lower()
    if not valid_email(email):
        raise HandledError("invalid_email", 400)

    row = Signatures.get_by_id(signature_id)
    if row is None:
        raise HandledError("signature_not_found", 404)

    if datetime.now(timezone.utc) > row.created_at + SIGNING_WINDOW:
        raise HandledError("signature_expired", 410)

    if row.stage != SignatureStage.FORM.value:
        raise HandledError("signature_not_in_form_stage", 409)

    updated = Signatures.set_email(signature_id, email)

    response = {
        "id": updated.id,
        "stage": updated.stage,
        "email": updated.email,
    }

    return generate_response(response, 200)
