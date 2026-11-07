"""Unit tests for documents/confirm_reuse (FA1 -- parte 2: confirma y escribe).

Separado de check_reuse (que solo lee) por CQRS ligero: este es el único
handler de C11, además de on_upload, que efectivamente crea una fila
`validado` sin pasar por OCR.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4


def _event(body, authorized=True):
    headers = {"authorization": "Bearer faketoken"} if authorized else {}
    return {"headers": headers, "body": json.dumps(body) if body is not None else None}


def _source_doc(*, stage="validado", dias_desde_validacion=10, process_id=None, document_type="id_front"):
    return MagicMock(
        id=uuid4(),
        process_id=process_id or uuid4(),
        stage=stage,
        document_type=document_type,
        s3_key_evidence="evidencia-validada/otro-proceso/id_front/abc.jpg",
        hash_sha256="b" * 64,
        validated_at=datetime.now(timezone.utc) - timedelta(days=dias_desde_validacion),
    )


def _wire(h, monkeypatch, *, source, user_id=None, process_owner_id=None, source_owner_id=None,
          nuevo_documento=None, documentos_existentes_en_destino=()):
    user_id = user_id or uuid4()
    process_owner_id = process_owner_id if process_owner_id is not None else user_id
    source_owner_id = source_owner_id if source_owner_id is not None else user_id
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

    def _get_process(pid):
        if pid == source.process_id:
            return MagicMock(user_id=source_owner_id)
        return MagicMock(user_id=process_owner_id)

    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(side_effect=_get_process)))
    nuevo = nuevo_documento or MagicMock(
        id=uuid4(), public_dict=MagicMock(return_value={"id": "nuevo", "stage": "validado"})
    )
    monkeypatch.setattr(
        h,
        "Documentos",
        MagicMock(
            get_by_id=MagicMock(return_value=source),
            register_reused=MagicMock(return_value=nuevo),
            list_by_process=MagicMock(return_value=list(documentos_existentes_en_destino)),
        ),
    )
    monkeypatch.setattr(h, "DocumentEvents", MagicMock(record=MagicMock()))
    return user_id, nuevo


def test_reutiliza_un_documento_vigente(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    source = _source_doc()
    user_id, nuevo = _wire(h, monkeypatch, source=source)

    resp = h.handler(
        _event({"process_id": str(process_id), "document_type": "id_front", "source_document_id": str(source.id)}),
        None,
    )

    assert resp["statusCode"] == 200
    h.Documentos.register_reused.assert_called_once()
    _, kwargs = h.Documentos.register_reused.call_args
    assert kwargs["source"] is source
    h.DocumentEvents.record.assert_called_once()
    assert h.DocumentEvents.record.call_args.kwargs["event_type"] == "documento_reutilizado"


def test_rechaza_si_el_documento_origen_no_esta_validado(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    source = _source_doc(stage="rechazado")
    _wire(h, monkeypatch, source=source)

    resp = h.handler(
        _event({"process_id": str(process_id), "document_type": "id_front", "source_document_id": str(source.id)}),
        None,
    )

    assert resp["statusCode"] == 409
    h.Documentos.register_reused.assert_not_called()


def test_rechaza_si_el_documento_origen_ya_vencio(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    source = _source_doc(dias_desde_validacion=400)
    _wire(h, monkeypatch, source=source)

    resp = h.handler(
        _event({"process_id": str(process_id), "document_type": "id_front", "source_document_id": str(source.id)}),
        None,
    )

    assert resp["statusCode"] == 409
    h.Documentos.register_reused.assert_not_called()


def test_404_si_el_documento_origen_no_pertenece_al_usuario(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    source = _source_doc()
    _wire(h, monkeypatch, source=source, source_owner_id=uuid4())

    resp = h.handler(
        _event({"process_id": str(process_id), "document_type": "id_front", "source_document_id": str(source.id)}),
        None,
    )

    assert resp["statusCode"] == 404
    h.Documentos.register_reused.assert_not_called()


def test_404_si_el_proceso_destino_no_pertenece_al_usuario(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    source = _source_doc()
    _wire(h, monkeypatch, source=source, process_owner_id=uuid4())

    resp = h.handler(
        _event({"process_id": str(process_id), "document_type": "id_front", "source_document_id": str(source.id)}),
        None,
    )

    assert resp["statusCode"] == 404


def test_requiere_autenticacion(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    source = _source_doc()
    _wire(h, monkeypatch, source=source)

    resp = h.handler(
        _event(
            {"process_id": str(process_id), "document_type": "id_front", "source_document_id": str(source.id)},
            authorized=False,
        ),
        None,
    )

    assert resp["statusCode"] == 401


def test_rechaza_si_el_document_type_declarado_no_coincide_con_el_origen(load_handler, monkeypatch):
    # El documento origen es un id_front real; el cliente pide reutilizarlo
    # pero declarando un document_type distinto. No debe crear una fila
    # nueva con un document_type que no corresponde a la evidencia real.
    h = load_handler(__file__)
    process_id = uuid4()
    source = _source_doc(document_type="id_front")
    _wire(h, monkeypatch, source=source)

    resp = h.handler(
        _event({"process_id": str(process_id), "document_type": "rut", "source_document_id": str(source.id)}),
        None,
    )

    assert resp["statusCode"] == 409
    h.Documentos.register_reused.assert_not_called()


def test_rechaza_si_el_proceso_destino_ya_tiene_un_documento_validado_de_ese_tipo(load_handler, monkeypatch):
    # Confirmar una reutilización cuando el proceso actual ya tiene su
    # propio id_front validado duplicaría el expediente sin necesidad --
    # es exactamente el caso que el frontend ya evita ofrecer, pero el
    # backend no debe depender de que el cliente se porte bien.
    h = load_handler(__file__)
    process_id = uuid4()
    source = _source_doc()
    ya_validado = MagicMock(document_type="id_front", stage="validado")
    _wire(h, monkeypatch, source=source, documentos_existentes_en_destino=[ya_validado])

    resp = h.handler(
        _event({"process_id": str(process_id), "document_type": "id_front", "source_document_id": str(source.id)}),
        None,
    )

    assert resp["statusCode"] == 409
    h.Documentos.register_reused.assert_not_called()
