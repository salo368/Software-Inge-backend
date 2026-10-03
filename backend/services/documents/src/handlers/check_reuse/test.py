"""Unit tests for documents/check_reuse (FA1 -- parte 1: ¿hay algo reutilizable?).

Mismo patrón de mock de autenticación que upload_url/test.py y
get_status/test.py: se parchea a nivel de `libs.utils.auth` (donde
`@require_auth` las referencia), no una función `verify_token` que puede
dejar de existir en una refactorización interna.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4


def _event(process_id, document_type="id_front", authorized=True):
    headers = {"authorization": "Bearer faketoken"} if authorized else {}
    return {
        "headers": headers,
        "queryStringParameters": {"process_id": str(process_id), "document_type": document_type},
    }


def _vigente_doc(**overrides):
    base = {
        "id": uuid4(),
        "document_type": "id_front",
        "hash_sha256": "a" * 64,
        "validated_at": datetime.now(timezone.utc) - timedelta(days=10),
    }
    base.update(overrides)
    return MagicMock(**base)


def _wire(h, monkeypatch, *, documento_vigente, user_id=None, process_owner_id=None):
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
    monkeypatch.setattr(
        h, "Documentos", MagicMock(get_vigente=MagicMock(return_value=documento_vigente))
    )
    return user_id


def test_reutilizable_cuando_hay_un_documento_vigente(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    _wire(h, monkeypatch, documento_vigente=_vigente_doc())

    resp = h.handler(_event(process_id), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["reutilizable"] is True
    assert body["documento"]["hash_sha256"] == "a" * 64


def test_no_reutilizable_cuando_no_hay_documento_validado_previo(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    _wire(h, monkeypatch, documento_vigente=None)

    resp = h.handler(_event(process_id), None)

    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["reutilizable"] is False


def test_no_reutilizable_cuando_el_documento_encontrado_ya_vencio(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    vencido = _vigente_doc(validated_at=datetime.now(timezone.utc) - timedelta(days=400))
    _wire(h, monkeypatch, documento_vigente=vencido)

    resp = h.handler(_event(process_id), None)

    body = json.loads(resp["body"])
    assert body["reutilizable"] is False


def test_requiere_autenticacion(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    _wire(h, monkeypatch, documento_vigente=None)

    resp = h.handler(_event(process_id, authorized=False), None)

    assert resp["statusCode"] == 401


def test_404_cuando_el_proceso_no_pertenece_al_usuario(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    _wire(h, monkeypatch, documento_vigente=_vigente_doc(), user_id=uuid4(), process_owner_id=uuid4())

    resp = h.handler(_event(process_id), None)

    assert resp["statusCode"] == 404
