"""Public read of a ceremony. The token in the path is the only credential,
so nothing identifying leaks: the email comes back masked and the document is
handed over as a short-lived presigned URL.
"""
import os

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.core.s3 import presign_download
from libs.orm.signatures import Signatures

BUCKET = os.environ["FILES_BUCKET"]


@handle_exceptions
def handler(event, context):
    token = (event.get("pathParameters") or {}).get("token", "")
    row = Signatures.get_by_token(token)
    if row is None:
        raise HandledError("signature_not_found", 404)

    payload = row.public_dict()
    payload["pdf_url"] = presign_download(BUCKET, row.pdf_key)
    if row.signed_pdf_key:
        payload["signed_pdf_url"] = presign_download(BUCKET, row.signed_pdf_key)
    return generate_response(payload)
