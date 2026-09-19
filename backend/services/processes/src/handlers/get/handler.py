from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.files import Files
from libs.orm.processes import Processes
from libs.orm.signatures import Signatures
from libs.utils.auth import require_auth


@handle_exceptions
@require_auth
def handler(event, context):
    pid_raw = (event.get("pathParameters") or {}).get("id")
    try:
        pid = UUID(pid_raw)
    except (TypeError, ValueError):
        raise HandledError("invalid process id", 400)

    proc = Processes.get_by_id(pid)
    if proc is None or proc.user_id != event["user"].id:
        raise HandledError("process_not_found", 404)

    files = [f.public_dict() for f in Files.list_by_process(proc.id)]
    ceremony = Signatures.get_active_for_process(proc.id)
    return generate_response({
        "process": proc.public_dict(),
        "files": files,
        "signature": ceremony.public_dict() if ceremony else None,
    })
