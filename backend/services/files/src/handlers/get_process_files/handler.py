import os

from libs.core.responses import generate_response, handle_exceptions
from libs.core.s3 import presign_download
from libs.orm.files import Files
from libs.utils.auth import AuthsTypes, require_auth
from libs.utils.params import request_params, uuid_param

BUCKET = os.environ["FILES_BUCKET"]


@handle_exceptions
@require_auth(AuthsTypes.INTERNAL)
def handler(event, context):

    process_id = uuid_param(request_params(event), "process_id", "invalid process id")

    rows = Files.list_by_process(process_id)

    files = [
        {
            "id": row.id,
            "file_type": row.file_type,
            "original_name": row.original_name,
            "content_type": row.content_type,
            "size_bytes": row.size_bytes,
            "uploaded_at": row.uploaded_at,
            "url": presign_download(BUCKET, row.s3_key),
        }
        for row in rows
    ]

    return generate_response({"files": files}, 200)
