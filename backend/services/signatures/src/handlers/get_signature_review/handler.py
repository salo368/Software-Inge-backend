import os

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.core.s3 import presign_download
from libs.orm.signatures import BIOMETRIC_COLUMNS, SIGNING_WINDOW, Signatures
from libs.utils.auth import AuthsTypes, require_auth
from libs.utils.params import request_params, uuid_param

BUCKET = os.environ["SIGNATURES_BUCKET"]

# The telemetry resolve_otp stores in signing_data (also printed on the
# evidence page of the signed PDF).
_TELEMETRY_KEYS = ("ip", "user_agent", "accept_language", "resolved_at")


def _url(key):
    return presign_download(BUCKET, key) if key else None


@handle_exceptions
@require_auth(AuthsTypes.INTERNAL)
def handler(event, context):

    signature_id = uuid_param(request_params(event), "signature_id", "invalid signature id")

    row = Signatures.get_by_id(signature_id)
    if row is None:
        raise HandledError("signature_not_found", 404)

    signing_data = row.signing_data or {}

    response = {
        "id": row.id,
        "stage": row.stage,
        "signatory": row.signatory,
        "email": row.email,
        "created_at": row.created_at,
        "expires_at": row.created_at + SIGNING_WINDOW,
        "signed_at": row.signed_at,
        "otp_tries": row.otp_tries,
        "doc_hash": row.doc_hash,
        "signed_hash": row.signed_hash,
        "telemetry": {key: signing_data.get(key) for key in _TELEMETRY_KEYS},
        "doc_url": _url(row.doc_s3_key),
        "raw_signed_url": _url(row.raw_signed_s3_key),
        "signed_url": _url(row.signed_s3_key),
        "draw_url": _url(row.draw_s3_key),
        "evidences": {kind: _url(getattr(row, column)) for kind, column in BIOMETRIC_COLUMNS.items()},
    }

    return generate_response(response, 200)
