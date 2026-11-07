"""S3 ObjectCreated trigger: el mecanismo central de C11.

Event-Driven Consumer (Enterprise Integration Pattern) -- igual disparador
que `files/on_upload`, pero este worker SÍ ejecuta lógica de dominio (a
diferencia de `files`, que solo registra metadata). Es la pieza que hace
cumplir Q04R01 (no bloquear la interfaz): el handler `upload_url` responde
en milisegundos, y todo el trabajo pesado (OCR + matching) ocurre aquí,
asíncrono, disparado por el propio evento de S3.

Keys esperadas: `transactions/{process_id}/{document_type}/{uuid}.{ext}`
(mismo esquema que `files/on_upload`, mismo prefijo `transactions/` que
`signatures` usa para datos de vida corta).

Pipeline (Functional Core, Imperative Shell -- este módulo es el "shell":
I/O, orquestación; toda la regla de negocio vive en `domain.matching`,
funciones puras):

    1. Idempotencia: si la key ya fue procesada, no hacer nada (igual
       criterio que `files/on_upload`).
    2. Descargar el archivo + los datos declarados por el inversionista
       (`Processes` -> `Forms.full_name`).
    3. `domain.matching.evaluar_formato` -> si los bytes no corresponden al
       tipo que la extensión de la key declara, o el tamaño está fuera de
       rango: rechazar (FE1, motivo `formato_no_admitido`) ANTES de gastar
       un ciclo de OCR.
    4. Extraer texto vía el puerto `DocumentExtractor` (Strategy:
       `TesseractAdapter` por defecto).
    5. `domain.matching.evaluar_legibilidad` -> si no es legible: rechazar
       (FE1, motivo `documento_ilegible`), sin calcular hash ni mover el
       archivo.
    6. `domain.matching.corresponde_con_declarado` -> si no corresponde:
       rechazar (motivo `no_corresponde`).
    7. Si corresponde: hash SHA-256 (Q20R01, integridad) + copia a
       `evidencia-validada/` (Tiered Storage, Q22R03, retención 10 años).
    8. Auditoría (Q22R01): un evento append-only por cada transición, sin
       excepción -- carga, y el resultado final (validado o rechazado).
"""
from __future__ import annotations

import hashlib

from libs.core.db import db_session
from libs.core.logger import Logger
from libs.core.s3 import download_bytes, upload_from_bytes
from libs.orm.documents import DocumentEvents, Documentos
from libs.orm.forms import Forms
from libs.orm.processes import Processes

from domain.adapters.tesseract_adapter import TesseractAdapter
from domain.matching import corresponde_con_declarado, evaluar_formato, evaluar_legibilidad
from domain.ports import ExtractedFields, ExtractedWord

# Strategy pattern: una sola variable decide el adaptador activo. El modo
# cloud (Azure AI Document Intelligence) se agrega en un slice siguiente
# sin tocar este módulo -- solo una rama más aquí.
_extractor = TesseractAdapter()

# FE1: el evento S3 no trae el content-type declarado al pedir la URL
# prefirmada, así que se infiere de la extensión que upload_url ya
# codificó en la propia key (ver _EXT_BY_CONTENT_TYPE en upload_url/
# handler.py). Una extensión no reconocida se trata como formato no
# admitido, igual que unos bytes que no coincidan con la extensión.
_EXT_TO_CONTENT_TYPE = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}


def handler(event, context):
    for record in event.get("Records", []):
        try:
            _process_record(record)
        except Exception as e:
            Logger.log("ERROR", f"documents/on_upload failed for {record}: {e}")
    db_session.commit()
    return {"processed": len(event.get("Records", []))}


def _process_record(record: dict) -> None:
    from urllib.parse import unquote_plus

    s3 = record["s3"]
    bucket = s3["bucket"]["name"]
    key = unquote_plus(s3["object"]["key"])

    parts = key.split("/")
    if len(parts) < 4 or parts[0] != "transactions":
        Logger.log("WARNING", f"documents/on_upload: ignoring unexpected key {key}")
        return

    _, process_id, document_type, _filename = parts[0], parts[1], parts[2], "/".join(parts[3:])

    if Documentos.get_by_s3_key(key) is not None:
        Logger.log("INFO", f"documents/on_upload: already processed {key}")
        return

    proc = Processes.get_by_id(process_id)
    if proc is None:
        Logger.log("WARNING", f"documents/on_upload: unknown process {process_id}")
        return
    form = Forms.get_by_user(proc.user_id)
    nombre_declarado = form.full_name if form is not None else ""

    row = Documentos.register_from_s3(process_id=process_id, document_type=document_type, s3_key_raw=key)
    DocumentEvents.record(document_id=row.id, event_type="documento_cargado", actor=str(proc.user_id))

    data = download_bytes(bucket, key)

    ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    content_type = _EXT_TO_CONTENT_TYPE.get(ext, "")
    formato = evaluar_formato(data, content_type=content_type)
    if not formato.valido:
        row.mark_rechazado(reason=formato.reason)
        DocumentEvents.record(
            document_id=row.id, event_type="documento_rechazado",
            actor="system", result=formato.reason,
        )
        return

    fields = _extractor.extract(data)

    legibilidad = evaluar_legibilidad(fields)
    if not legibilidad.legible:
        row.mark_rechazado(reason=legibilidad.reason)
        DocumentEvents.record(
            document_id=row.id, event_type="documento_rechazado",
            actor="system", result=legibilidad.reason,
        )
        return

    correspondencia = corresponde_con_declarado(fields, nombre_declarado=nombre_declarado)
    if not correspondencia.corresponde:
        row.mark_rechazado(reason="no_corresponde")
        DocumentEvents.record(
            document_id=row.id, event_type="documento_rechazado",
            actor="system", result="no_corresponde",
        )
        return

    hash_sha256 = hashlib.sha256(data).hexdigest()
    evidence_key = key.replace("transactions/", "evidencia-validada/", 1)
    upload_from_bytes(bucket, evidence_key, data)

    row.mark_validado(s3_key_evidence=evidence_key, hash_sha256=hash_sha256)
    DocumentEvents.record(
        document_id=row.id, event_type="documento_validado",
        actor="system", result="validado",
    )
