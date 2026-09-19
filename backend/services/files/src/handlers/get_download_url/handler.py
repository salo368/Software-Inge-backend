import os
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.core.s3 import presign_download
from libs.orm.files import Files
from libs.orm.processes import Processes
from libs.utils.auth import require_auth

BUCKET = os.environ["FILES_BUCKET"]


@handle_exceptions
@require_auth
def handler(event, context):
    file_id_raw = (event.get("pathParameters") or {}).get("id")
    try:
        file_id = UUID(file_id_raw)
    except (TypeError, ValueError):
        raise HandledError("invalid file id", 400)

    file_row = Files.get_by_id(file_id)
    if file_row is None:
        raise HandledError("file_not_found", 404)

    process = Processes.get_by_id(file_row.process_id)
    if process is None or process.user_id != event["user"].id:
        raise HandledError("file_not_found", 404)

    url = presign_download(BUCKET, file_row.s3_key, filename=file_row.original_name)
    return generate_response({
        "download_url": url,
        "content_type": file_row.content_type,
        "original_name": file_row.original_name,
        "expires_in": 900,
    })
