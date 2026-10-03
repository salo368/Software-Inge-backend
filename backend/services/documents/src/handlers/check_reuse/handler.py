"""FA1 (Alternativo · Reutilización de vigentes, catálogo C11) -- parte 1.

Indica si el inversionista ya tiene, de cualquier proceso anterior, un
documento del mismo tipo validado y todavía dentro de la ventana de
vigencia (domain.vigencia). No modifica nada: es una consulta, separada
a propósito de confirm_reuse (que sí escribe), mismo criterio de CQRS
ligero que ya separa upload_url/get_status.
"""
from __future__ import annotations

from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.documents import Documentos
from libs.orm.processes import Processes
from libs.utils.auth import require_auth

from domain.vigencia import es_vigente


@handle_exceptions
@require_auth
def handler(event, context):
    user = event["user"]
    params = event.get("queryStringParameters") or {}
    document_type = params.get("document_type")
    if not document_type:
        raise HandledError("missing_document_type", 400)

    try:
        process_id = UUID(params.get("process_id"))
    except (TypeError, ValueError):
        raise HandledError("invalid_process_id", 400)

    proc = Processes.get_by_id(process_id)
    # Mismo criterio anti-enumeración que get_status/processes.get: dueño
    # incorrecto responde 404, no 403.
    if proc is None or proc.user_id != user.id:
        raise HandledError("process_not_found", 404)

    documento = Documentos.get_vigente(user_id=user.id, document_type=document_type)
    if documento is None or not es_vigente(documento.validated_at):
        return generate_response({"reutilizable": False})

    return generate_response({
        "reutilizable": True,
        "documento": {
            "id": str(documento.id),
            "document_type": documento.document_type,
            "validated_at": documento.validated_at.isoformat(),
            "hash_sha256": documento.hash_sha256,
        },
    })
