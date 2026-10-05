"""FA1 (Alternativo · Reutilización de vigentes, catálogo C11) -- parte 2.

Confirma la reutilización que `check_reuse` ofreció y crea el documento
`validado` en el proceso actual, sin pasar por OCR. No confía en que el
cliente haya llamado a check_reuse primero: vuelve a verificar aquí que
el documento origen siga siendo del mismo usuario, esté validado y
todavía esté vigente (guarda defensiva -- el tiempo entre las dos
llamadas HTTP es suficiente para que el documento haya vencido).

Dos guardas adicionales, encontradas en revisión antes de abrir el PR,
no en el diseño original: el document_type que llega en el cuerpo debe
coincidir con el de la evidencia real (nunca se toma como dado solo
porque el cliente lo declaró), y el proceso destino no puede ya tener un
documento validado del mismo tipo (evita un expediente duplicado si
alguien llama a este endpoint sin pasar por check_reuse primero).
"""
from __future__ import annotations

import json
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.documents import Documentos, DocumentEvents
from libs.orm.processes import Processes
from libs.utils.auth import require_auth

from domain.vigencia import es_vigente


@handle_exceptions
@require_auth
def handler(event, context):
    user = event["user"]
    body = json.loads(event.get("body") or "{}")

    document_type = body.get("document_type")
    if not document_type:
        raise HandledError("missing_document_type", 400)

    try:
        process_id = UUID(body.get("process_id"))
        source_document_id = UUID(body.get("source_document_id"))
    except (TypeError, ValueError):
        raise HandledError("invalid_id", 400)

    proc = Processes.get_by_id(process_id)
    if proc is None or proc.user_id != user.id:
        raise HandledError("process_not_found", 404)

    source = Documentos.get_by_id(source_document_id)
    if source is None:
        raise HandledError("source_document_not_found", 404)

    source_proc = Processes.get_by_id(source.process_id)
    # Mismo criterio anti-enumeración: un documento de otro usuario no
    # distingue su respuesta de "no existe".
    if source_proc is None or source_proc.user_id != user.id:
        raise HandledError("source_document_not_found", 404)

    if source.stage != "validado" or not es_vigente(source.validated_at):
        raise HandledError("documento_no_reutilizable", 409)

    # El document_type declarado debe corresponder a la evidencia real que
    # se está reutilizando -- nunca se toma como dado solo porque vino en
    # el cuerpo de la petición. Sin esto, un cliente podría pedir que un
    # id_front validado se registre bajo cualquier otro document_type.
    if source.document_type != document_type:
        raise HandledError("document_type_no_coincide_con_el_origen", 409)

    # El proceso destino no debe terminar con dos documentos validado del
    # mismo tipo -- es el mismo caso que el frontend ya evita ofrecer
    # (no se llama a check_reuse si ya hay un id_front validado), pero el
    # backend no puede depender de que el cliente respete esa regla.
    ya_tiene_validado = any(
        d.document_type == document_type and d.stage == "validado"
        for d in Documentos.list_by_process(process_id)
    )
    if ya_tiene_validado:
        raise HandledError("proceso_ya_tiene_documento_validado", 409)

    nuevo = Documentos.register_reused(process_id=process_id, document_type=document_type, source=source)
    DocumentEvents.record(
        document_id=nuevo.id, event_type="documento_reutilizado",
        actor=str(user.id), result="validado",
    )

    return generate_response(nuevo.public_dict())
