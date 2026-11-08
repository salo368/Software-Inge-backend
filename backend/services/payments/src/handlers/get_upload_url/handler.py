import json
import os
from uuid import UUID, uuid4

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.core.s3 import presign_upload
from libs.utils.auth import require_auth
from utils.process_lookup import get_payable_process
from utils.s3_keys import build_payment_key

BUCKET = os.environ["FILES_BUCKET"]

EXTENSION_BY_CONTENT_TYPE = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


@handle_exceptions
@require_auth
def handler(event, context):

    body = json.loads(event.get("body") or "{}")

    try:
        process_id = UUID(body.get("process_id"))
    except (TypeError, ValueError):
        raise HandledError("invalid process id", 400)

    content_type = body.get("content_type", "image/jpeg")
    if content_type not in EXTENSION_BY_CONTENT_TYPE:
        raise HandledError(f"content_type must be one of {sorted(EXTENSION_BY_CONTENT_TYPE)}", 400)

    get_payable_process(event, process_id)

    key = build_payment_key(process_id, uuid4(), EXTENSION_BY_CONTENT_TYPE[content_type])
    url = presign_upload(BUCKET, key, content_type)

    response = {
        "upload_url": url,
        "key": key,
        "content_type": content_type,
        "upload_headers": {"Content-Type": content_type},
        "expires_in": 900,
    }

    return generate_response(response, 200)
