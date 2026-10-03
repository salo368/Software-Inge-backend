"""Unit tests for documents/upload_url.

El handler usa el decorador @require_auth (no una función `verify_token`
importada directo), así que el mock de autenticación se hace a nivel de
las clases ORM que `require_auth` consulta internamente
(`BearerTokens.get_by_hash`, `Users.get_by_id`) -- vía su ruta de módulo
completa, no vía `h.<nombre>`, porque el handler no las importa él mismo.
Esto es deliberado: es robusto frente a cómo libs/utils/auth.py reorganice
su lógica interna (a diferencia de parchear una función interna como
`verify_token`, que puede dejar de existir en una refactorización -- ver
el hallazgo documentado en C11_Arquitectura_Mecanismos_y_Patrones.md).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4


def _event(body: dict | None, authorized: bool = True) -> dict:
    headers = {"authorization": "Bearer faketoken"} if authorized else {}
    return {"headers": headers, "body": json.dumps(body) if body is not None else None}


def _wire(h, monkeypatch, *, user=None):
    user = user or MagicMock(id=uuid4())
    bearer = MagicMock(
        revoked_at=None,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        user_id=user.id,
    )
    bearer.is_alive.return_value = True
    # Parcheado donde `require_auth` las referencia (`libs.utils.auth`,
    # que las importa con `from libs.orm.X import Y`), no en su módulo de
    # origen -- si se parcha en el origen, el binding que `auth.py` ya
    # resolvió al importar no se entera del cambio.
    monkeypatch.setattr(
        "libs.utils.auth.BearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=bearer)),
    )
    monkeypatch.setattr(
        "libs.utils.auth.Users", MagicMock(get_by_id=MagicMock(return_value=user))
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
