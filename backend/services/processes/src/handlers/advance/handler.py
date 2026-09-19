"""Advances a process to the next stage.

Stages: form -> documents -> signature -> payment -> done

Gates:
  form       : the user must have a Forms row (upserted via /forms/me).
               We snapshot it into process.form_snapshot.
  documents  : at least one file of type `declaracion_renta` must be present.
  signature  : mocked. Any advance call moves it to `payment`.
  payment    : mocked. Any advance call moves it to `done`.
  done       : idempotent; returns the process untouched.
"""
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.files import Files
from libs.orm.forms import Forms
from libs.orm.processes import Processes
from libs.utils.auth import require_auth

NEXT_STAGE = {
    "form": "documents",
    "documents": "signature",
    "signature": "payment",
    "payment": "done",
}


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

    if proc.stage == "done":
        return generate_response({"process": proc.public_dict()})

    if proc.stage == "form":
        form = Forms.get_by_user(event["user"].id)
        if form is None:
            raise HandledError("form_required", 400)
        proc.form_snapshot = form.public_dict()

    elif proc.stage == "documents":
        files = Files.list_by_process(proc.id)
        if not any(f.file_type == "declaracion_renta" for f in files):
            raise HandledError("declaracion_renta_required", 400)

    proc.advance_to(NEXT_STAGE[proc.stage])
    return generate_response({"process": proc.public_dict()})
