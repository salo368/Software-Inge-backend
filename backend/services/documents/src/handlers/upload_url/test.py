"""Unit tests for documents/upload_url."""
from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4


def _event(body: dict | None, authorized: bool = True) -> dict:
    headers = {"authorization": "Bearer faketoken"} if authorized else {}
    return {"headers": headers, "body": json.dumps(body) if body is not None else None}


def _wire(h, monkeypatch, *, user=None):
    user = user or MagicMock(id=uuid4())
    monkeypatch.setattr(
        h, "verify_token", MagicMock(return_value=(user, MagicMock()))
    )
    monkeypatch.setattr(
        h,
        "presign_upload",
        MagicMock(return_value="https://s3.example.com/presigned-put"),
    )
    return user


def test_genera_url_presignada_para_tipo_valido(load_handler, monkeypatch):
    h = load_handler(__file__)
    _wire(h, monkeypatch)

    resp = h.handler(
        _event({"process_id": str(uuid4()), "document_type": "id_front", "content_type": "image/jpeg"}),
        None,
    )

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["upload_url"] == "https://s3.example.com/presigned-put"
    assert "key" in body
    h.presign_upload.assert_called_once()


def test_rechaza_tipo_de_documento_no_reconocido(load_handler, monkeypatch):
    h = load_handler(__file__)
    _wire(h, monkeypatch)

    resp = h.handler(
        _event({"process_id": str(uuid4()), "document_type": "pasaporte_marciano", "content_type": "image/jpeg"}),
        None,
    )

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "invalid_document_type"


def test_requiere_autenticacion(load_handler, monkeypatch):
    h = load_handler(__file__)
    _wire(h, monkeypatch)

    resp = h.handler(
        _event({"process_id": str(uuid4()), "document_type": "id_front", "content_type": "image/jpeg"}, authorized=False),
        None,
    )

    assert resp["statusCode"] == 401


def test_key_sigue_el_esquema_transactions_prefix(load_handler, monkeypatch):
    h = load_handler(__file__)
    _wire(h, monkeypatch)
    process_id = str(uuid4())

    resp = h.handler(
        _event({"process_id": process_id, "document_type": "id_front", "content_type": "image/jpeg"}),
        None,
    )

    body = json.loads(resp["body"])
    assert body["key"].startswith(f"transactions/{process_id}/id_front/")
    assert "evidencia-validada" not in body["key"]
