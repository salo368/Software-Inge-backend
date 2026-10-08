"""Deploy-verification tests for documents/upload_url + documents/on_upload
worker (the flagship end-to-end test, same role as
`files/get_upload_url/integration.py`).

Exercises the full real pipeline: POST /documents/upload-url -> PUT to S3
-> S3 ObjectCreated triggers the on_upload worker -> domain validation ->
GET /documents/status polled until a terminal stage.

Two cases, with very different expectations today:

  * test_formato_no_admitido_marca_rechazado_end_to_end (FE1) is fully
    deterministic: evaluar_formato runs BEFORE the OCR extractor, so it
    never touches Tesseract. This one should pass as soon as the service
    is deployed.

  * test_documento_legible_y_correspondiente_marca_validado_end_to_end
    (FB happy path) uploads a real JPEG with real rendered text and
    expects stage='validado'. As of this commit it is EXPECTED TO FAIL
    (or time out waiting for a terminal stage): the deployed Lambda has
    no `tesseract` binary packaged (see services/documents/domain/
    adapters/tesseract_adapter.py), only the `pytesseract` Python wrapper,
    so the worker cannot actually run OCR yet. The test is written now,
    on purpose, so that fixing the OCR packaging gap has an immediate,
    objective, already-written pass/fail signal instead of a second round
    of manual verification -- this is the gap documented in
    Revision_Pipelines_Pruebas_Integracion.md.

Gated by --integration (see backend/conftest.py).
"""
from __future__ import annotations

import os

import pytest
import requests

from tests.integration_documents import (
    DOCUMENTS_BUCKET,
    documents_api,
    insert_form_directly,
    insert_process_directly,
    make_garbage_bytes,
    make_test_jpeg,
    pick_active_bank_id,
)
from tests.integration_helpers import (
    bearer,
    cleanup_process,
    cleanup_s3_prefix,
    cleanup_user,
    create_test_user_directly,
    wait_for,
)

pytestmark = pytest.mark.integration


def _upload_and_poll(*, token: str, process_id: str, payload: bytes, content_type: str):
    """Shared steps for both tests: ask for a presigned URL, PUT the bytes,
    poll GET /documents/status until the row leaves 'pendiente'/'validando'.
    Returns (s3_key, final_row_or_None)."""
    url_resp = requests.post(
        f"{documents_api()}/documents/upload-url",
        headers=bearer(token),
        json={"process_id": process_id, "document_type": "id_front", "content_type": content_type},
        timeout=15,
    )
    assert url_resp.status_code == 200, url_resp.text
    url_body = url_resp.json()
    upload_url = url_body["upload_url"]
    s3_key = url_body["key"]
    assert s3_key.startswith(f"transactions/{process_id}/id_front/")

    put_resp = requests.put(upload_url, data=payload, headers={"Content-Type": content_type}, timeout=30)
    assert put_resp.status_code in (200, 204), put_resp.text

    def _poll():
        status_resp = requests.get(
            f"{documents_api()}/documents/status",
            headers=bearer(token),
            params={"process_id": process_id},
            timeout=15,
        )
        if status_resp.status_code != 200:
            return None
        rows = [d for d in status_resp.json()["documentos"] if d["document_type"] == "id_front"]
        if not rows:
            return None
        row = rows[0]
        return row if row["stage"] in ("validado", "rechazado") else None

    final_row = wait_for(_poll, timeout_s=45.0, interval_s=3.0)
    return s3_key, final_row


def test_formato_no_admitido_marca_rechazado_end_to_end():
    session = create_test_user_directly()
    email = session["email"]
    process_id: str | None = None

    try:
        bank_id = pick_active_bank_id()
        process_id = insert_process_directly(user_id=session["user_id"], bank_id=bank_id)

        _, final_row = _upload_and_poll(
            token=session["token"],
            process_id=process_id,
            payload=make_garbage_bytes(),
            content_type="image/jpeg",
        )

        assert final_row is not None, (
            "el worker nunca marco un estado terminal en 45s -- si esto falla, "
            "revisar primero si el evento S3 esta llegando al worker, no asumir "
            "que es el mismo gap de OCR (esta prueba nunca deberia llegar a OCR)"
        )
        assert final_row["stage"] == "rechazado"
        assert final_row["rejection_reason"] == "formato_no_admitido"
    finally:
        cleanup_s3_prefix(DOCUMENTS_BUCKET, f"transactions/{process_id}/")
        if process_id:
            cleanup_process(process_id)
        cleanup_user(email)


def test_documento_legible_y_correspondiente_marca_validado_end_to_end():
    session = create_test_user_directly()
    email = session["email"]
    full_name = "MARIA INTEGRATION TESTER"
    process_id: str | None = None

    try:
        bank_id = pick_active_bank_id()
        process_id = insert_process_directly(user_id=session["user_id"], bank_id=bank_id)
        insert_form_directly(user_id=session["user_id"], full_name=full_name)

        jpeg_bytes = make_test_jpeg(text=full_name)
        s3_key, final_row = _upload_and_poll(
            token=session["token"],
            process_id=process_id,
            payload=jpeg_bytes,
            content_type="image/jpeg",
        )

        assert final_row is not None, (
            "el worker nunca marco un estado terminal en 45s. Causa mas probable "
            "hoy: TesseractNotFoundError sin capturar en el worker porque el "
            "binario `tesseract` no esta empaquetado en el Lambda (ver "
            "services/documents/domain/adapters/tesseract_adapter.py y "
            "Revision_Pipelines_Pruebas_Integracion.md). Revisar CloudWatch del "
            "Lambda on_upload antes de asumir que es el umbral de legibilidad."
        )
        assert final_row["stage"] == "validado", (
            f"se esperaba 'validado', se obtuvo {final_row['stage']!r} "
            f"(motivo: {final_row.get('rejection_reason')!r}). Con OCR real "
            "funcionando, esto puede fallar igual por calidad de la imagen "
            "sintetica -- no asumir regresion de codigo sin revisar primero "
            "si el extractor corrio en absoluto (ver CloudWatch)."
        )
        assert final_row["hash_sha256"] is not None
    finally:
        cleanup_s3_prefix(DOCUMENTS_BUCKET, f"transactions/{process_id}/")
        cleanup_s3_prefix(DOCUMENTS_BUCKET, f"evidencia-validada/{process_id}/")
        if process_id:
            cleanup_process(process_id)
        cleanup_user(email)
