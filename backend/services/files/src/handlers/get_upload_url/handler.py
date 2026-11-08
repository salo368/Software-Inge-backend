import json
import os
from urllib.parse import quote
from uuid import UUID, uuid4

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.core.s3 import presign_upload
from libs.orm.files import FileType
from libs.orm.processes import Processes
from libs.utils.auth import require_auth
from utils.s3_keys import build_file_key, build_file_metadata

BUCKET = os.environ["FILES_BUCKET"]

ALLOWED_TYPES = {member.value for member in FileType}
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
}


@handle_exceptions
@require_auth
def handler(event, context):

    body = json.loads(event.get("body") or "{}")

    process_id_raw = body.get("process_id")
    file_type = body.get("file_type")
    content_type = body.get("content_type", "application/pdf")
    original_name = body.get("original_name")

    if not process_id_raw or not file_type:
        raise HandledError("process_id and file_type are required", 400)

    if file_type not in ALLOWED_TYPES:
        raise HandledError(f"file_type must be one of {sorted(ALLOWED_TYPES)}", 400)

    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HandledError("content_type not allowed", 400)

    try:
        process_id = UUID(process_id_raw)
    except (TypeError, ValueError):
        raise HandledError("invalid process_id", 400)

    process = Processes.get_by_id(process_id)
    if process is None or process.user_id != event["user"].id:
        raise HandledError("process_not_found", 404)

    file_id = uuid4()
    ext = _extension_for(content_type, original_name)
    key = build_file_key(process.id, file_type, file_id, ext)

    safe_name = quote(original_name or f"{file_id}{ext}", safe="")
    metadata = build_file_metadata(process.id, file_type, safe_name)

    url = presign_upload(BUCKET, key, content_type, metadata=metadata)

    response = {
        "upload_url": url,
        "key": key,
        "content_type": content_type,
        "upload_headers": {
            "Content-Type": content_type,
            **{f"x-amz-meta-{name}": value for name, value in metadata.items()},
        },
        "expires_in": 900,
    }

    return generate_response(response)


def _extension_for(content_type: str, original_name: str | None) -> str:

    if original_name and "." in original_name:
        return "." + original_name.rsplit(".", 1)[-1].lower()

    return {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/png": ".png",
    }.get(content_type, "")
