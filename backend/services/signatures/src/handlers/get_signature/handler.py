import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.core.s3 import presign_download
from libs.orm.signatures import Signatures

BUCKET = os.environ["SIGNATURES_BUCKET"]

SIGNING_WINDOW = timedelta(minutes=20)


@handle_exceptions
def handler(event, context):

    query_params = event.get("queryStringParameters") or {}

    signature_id_raw = query_params.get("signature_id")
    if not signature_id_raw:
        raise HandledError("signature_id is required", 400)
    try:
        signature_id = UUID(signature_id_raw)
    except ValueError:
        raise HandledError("invalid signature_id", 400)

    row = Signatures.get_by_id(signature_id)
    if row is None:
        raise HandledError("signature_not_found", 404)

    expires_at = row.created_at + SIGNING_WINDOW
    if datetime.now(timezone.utc) > expires_at:
        raise HandledError("signature_expired", 410)

    doc_url = presign_download(BUCKET, row.doc_s3_key)

    response = {
        "id": row.id,
        "stage": row.stage,
        "sign_location": row.sign_location,
        "doc_url": doc_url,
        "expires_at": expires_at,
    }

    return generate_response(response, 200)
