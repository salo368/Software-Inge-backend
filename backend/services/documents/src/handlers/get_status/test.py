"""Unit tests for documents/get_status (CQRS -- lado de lectura).

Ver la nota en upload_url/test.py: el mock de autenticación se hace a
nivel de `libs.utils.auth.BearerTokens`/`.Users` (donde @require_auth las
referencia), no de una función `verify_token` que puede dejar de existir
en una refactorización interna.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4


def _event(process_id, authorized: bool = True) -> dict:
    headers = {"authorization": "Bearer faketoken"} if authorized else {}
    return {"headers": headers, "queryStringParameters": {"process_id": str(process_id)}}


def _doc(**overrides):
    base = {
        "id": str(uuid4()),
        "document_type": "id_front",
        "stage": "pendiente",
        "rejection_reason": None,
        "hash_sha256": None,
        "uploaded_at": "2026-10-01T00:00:00+00:00",
        "validated_at": None,
    }
    base.update(overrides)
    return MagicMock(public_dict=MagicMock(return_value=base))


def _wire(h, monkeypatch, *, documentos, user_id=None, process_owner_id=None):
    user_id = user_id or uuid4()
    process_owner_id = process_owner_id if process_owner_id is not None else user_id
    user = MagicMock(id=user_id)
    bearer = MagicMock(
        revoked_at=None,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        user_id=user_id,
    )
    bearer.is_alive.return_value = True
    monkeypatch.setattr(
        "libs.utils.auth.BearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=bearer)),
    )
    monkeypatch.setattr("libs.utils.auth.Users", MagicMock(get_by_id=MagicMock(return_value=user)))
    monkeypatch.setattr(
        h, "Processes", MagicMock(get_by_id=MagicMock(return_value=MagicMock(user_id=process_owner_id)))
    )
    monkeypatch.setattr(h, "Documentos", MagicMock(list_by_process=MagicMock(return_value=documentos)))


def test_devuelve_pendiente_antes_de_procesar(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    _wire(h, monkeypatch, documentos=[_doc(stage="pendiente")])

    resp = h.handler(_event(process_id), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["documentos"][0]["stage"] == "pendiente"


def test_devuelve_validado_con_hash(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    _wire(h, monkeypatch, documentos=[_doc(stage="validado", hash_sha256="a" * 64)])

    resp = h.handler(_event(process_id), None)

    body = json.loads(resp["body"])
    assert body["documentos"][0]["stage"] == "validado"
    assert body["documentos"][0]["hash_sha256"] == "a" * 64


def test_devuelve_rechazado_con_motivo(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    _wire(h, monkeypatch, documentos=[_doc(stage="rechazado", rejection_reason="documento_ilegible")])

    resp = h.handler(_event(process_id), None)

    body = json.loads(resp["body"])
    assert body["documentos"][0]["rejection_reason"] == "documento_ilegible"


def test_requiere_autenticacion(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    _wire(h, monkeypatch, documentos=[])

    resp = h.handler(_event(process_id, authorized=False), None)

    assert resp["statusCode"] == 401


def test_no_devuelve_documentos_de_un_proceso_ajeno(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    _wire(h, monkeypatch, documentos=[_doc()], user_id=uuid4(), process_owner_id=uuid4())

    resp = h.handler(_event(process_id), None)

    assert resp["statusCode"] == 404
