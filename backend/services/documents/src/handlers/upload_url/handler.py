"""Genera una URL presignada de subida directa a S3 (Presigned URL / Direct-
to-Storage Upload) para un documento del expediente de C11.

No escribe nada en la base de datos -- mismo límite que
`files/get_upload_url`: la fila real (`Documentos`) la crea el worker
`on_upload` cuando el evento S3 confirma que el archivo llegó. Este handler
solo autentica, valida el tipo de documento y firma la URL.

Slice básico (FB): solo `id_front` es un tipo de documento válido. FA2
(documentación corporativa: RUT, certificado de existencia, etc.) agrega
más tipos en un slice siguiente -- no se adelanta aquí para no mezclar
scopes.
"""
from __future__ import annotations

import json
import os
from uuid import uuid4

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.core.s3 import presign_upload
from libs.utils.auth import require_auth

DOCUMENTS_BUCKET = os.environ["DOCUMENTS_BUCKET"]

# Slice básico: un único tipo de documento. Se extiende en el slice FA2.
VALID_DOCUMENT_TYPES = {"id_front"}

_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "application/pdf": "pdf",
}


@handle_exceptions
@require_auth
def handler(event, context):
    # Mismo mecanismo de auth que el resto de `portal` (Bearer token de
    # `auth`, vía el decorador @require_auth -- no una función
    # `verify_token` importada directo: esa es una pieza interna de
    # libs/utils/auth.py que puede reorganizarse con el tiempo; el
    # decorador es el contrato público estable que el resto del backend
    # ya usa). No es un capability-token nuevo tipo `sign_id` -- C11 vive
    # dentro del wizard autenticado, no detrás de un link público como
    # `signatures`.
    body = json.loads(event.get("body") or "{}")
    process_id = body.get("process_id")
    document_type = body.get("document_type")
    content_type = body.get("content_type") or "application/octet-stream"

    if not process_id:
        raise HandledError("missing_process_id", 400)
    if document_type not in VALID_DOCUMENT_TYPES:
        raise HandledError("invalid_document_type", 400)

    ext = _EXT_BY_CONTENT_TYPE.get(content_type, "bin")
    key = f"transactions/{process_id}/{document_type}/{uuid4()}.{ext}"

    upload_url = presign_upload(DOCUMENTS_BUCKET, key, content_type)

    return generate_response({
        "upload_url": upload_url,
        "key": key,
        "content_type": content_type,
    })
