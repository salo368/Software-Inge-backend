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

    # Signatures redesign (fase 2+): the ceremony no longer stores a
    # process_id foreign key -- the relationship is owned by processes
    # via `sign_id`. `Signatures.get_active_for_process` was removed in
    # that migration; we now look up the ceremony (if any) by the
    # process's sign_id column populated on the documents -> signature
    # transition (fase 6a).
    ceremony = (
        Signatures.get_by_sign_id(proc.sign_id) if proc.sign_id else None
    )
    return generate_response({
        "process": proc.public_dict(),
        "files": files,
        "signature": ceremony.public_dict() if ceremony else None,
    })
