import os
from datetime import datetime, timezone
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.core.s3 import presign_download
from libs.orm.signatures import SIGNING_WINDOW, SignatureStage, Signatures

BUCKET = os.environ["SIGNATURES_BUCKET"]

# SIGNING is included because it always resolves within SIGNING_TIMEOUT:
# a 410 at the window edge would stop the front from polling just before
# the row reaches SIGNED.
_NO_EXPIRY_STAGES = (
    SignatureStage.SIGNING.value,
    SignatureStage.SIGNED.value,
    SignatureStage.FAILED.value,
)


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
    if row.stage not in _NO_EXPIRY_STAGES and datetime.now(timezone.utc) > expires_at:
        raise HandledError("signature_expired", 410)

    doc_url = presign_download(BUCKET, row.doc_s3_key)
    raw_signed_url = presign_download(BUCKET, row.raw_signed_s3_key) if row.raw_signed_s3_key else None
    signed_url = presign_download(BUCKET, row.signed_s3_key) if row.signed_s3_key else None

    response = {
        "id": row.id,
        "stage": row.stage,
        "sign_location": row.sign_location,
        "doc_url": doc_url,
        "expires_at": expires_at,
        "raw_signed_url": raw_signed_url,
        "signed_url": signed_url,
        "doc_hash": row.doc_hash,
        "signed_hash": row.signed_hash,
        "signed_at": row.signed_at,
    }

    return generate_response(response, 200)
