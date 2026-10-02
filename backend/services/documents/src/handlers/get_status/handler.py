"""Consulta de solo lectura del expediente documental (CQRS, lado de
consulta -- separado del comando asíncrono `on_upload`). El frontend hace
polling de este endpoint para saber cuándo terminó la validación.
"""
from __future__ import annotations

from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.documents import Documentos
from libs.orm.processes import Processes
from libs.utils.auth import verify_token


def _extract_bearer(event) -> str:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    authz = headers.get("authorization", "")
    if not authz.lower().startswith("bearer "):
        raise HandledError("missing_bearer_token", 401)
    return authz[7:].strip()


@handle_exceptions
def handler(event, context):
    user, _ = verify_token(_extract_bearer(event))

    raw_process_id = (event.get("queryStringParameters") or {}).get("process_id")
    try:
        process_id = UUID(raw_process_id)
    except (TypeError, ValueError):
        raise HandledError("invalid_process_id", 400)

    proc = Processes.get_by_id(process_id)
    # Mismo criterio anti-enumeración que processes/get: dueño incorrecto
    # responde 404, no 403 -- no revela si el proceso existe.
    if proc is None or proc.user_id != user.id:
        raise HandledError("process_not_found", 404)

    documentos = [d.public_dict() for d in Documentos.list_by_process(process_id)]

    return generate_response({"process_id": str(process_id), "documentos": documentos})
