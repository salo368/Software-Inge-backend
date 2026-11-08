import json

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.files import Files


@handle_exceptions
def handler(event, context):

    body = json.loads(event.get("body") or "{}")

    process_id = body.get("process_id")
    if not process_id:
        raise HandledError("process_id is required", 400)

    rows = Files.list_by_process(process_id)

    files = []
    for row in rows:
        files.append({
            "id": row.id,
            "file_type": row.file_type,
            "original_name": row.original_name,
            "uploaded_at": row.uploaded_at,
        })

    response = {
        "files": files,
    }

    return generate_response(response, 200)
