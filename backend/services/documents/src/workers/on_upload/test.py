"""Unit tests for documents/on_upload (el mecanismo central de C11)."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4


def _s3_event(key: str, bucket: str = "cdts-test-documents") -> dict:
    return {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}


class _FakeExtractor:
    """Doble de prueba que cumple DocumentExtractor sin tocar Tesseract."""

    def __init__(self, fields):
        self._fields = fields
        self.calls = 0

    def extract(self, image_bytes: bytes):
        self.calls += 1
        return self._fields


def _legible_fields(h, nombre="JUAN PEREZ"):
    """Construye un ExtractedFields legible y correspondiente a `nombre`."""
    Word = h.ExtractedWord
    words = [Word(text=w, confidence=90.0, block_num=1, par_num=1, line_num=1) for w in nombre.split()]
    words += [Word(text=str(n), confidence=92.0, block_num=1, par_num=1, line_num=2) for n in range(1000, 1003)]
    return h.ExtractedFields(words=tuple(words))


def _ilegible_fields(h):
    Word = h.ExtractedWord
    return h.ExtractedFields(words=(Word(text="", confidence=97.0, block_num=1, par_num=1, line_num=1),))


def _wire(h, monkeypatch, *, process_id, document_type="id_front", extractor_fields, full_name="Juan Perez"):
    key = f"transactions/{process_id}/{document_type}/{uuid4()}.jpg"

    documento = MagicMock(id=uuid4(), stage="validando")
    monkeypatch.setattr(
        h,
        "Documentos",
        MagicMock(
            get_by_s3_key=MagicMock(return_value=None),
            register_from_s3=MagicMock(return_value=documento),
        ),
    )
    monkeypatch.setattr(h, "DocumentEvents", MagicMock(record=MagicMock()))
    monkeypatch.setattr(
        h, "Processes", MagicMock(get_by_id=MagicMock(return_value=MagicMock(user_id=uuid4())))
    )
    monkeypatch.setattr(
        h, "Forms", MagicMock(get_by_user=MagicMock(return_value=MagicMock(full_name=full_name)))
    )
    monkeypatch.setattr(h, "download_bytes", MagicMock(return_value=b"fake-image-bytes"))
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock())
    monkeypatch.setattr(h, "_extractor", _FakeExtractor(extractor_fields))
    monkeypatch.setattr(h.db_session, "commit", MagicMock())

    return key, documento


def test_marca_validado_cuando_es_legible_y_corresponde(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    key, documento = _wire(
        h, monkeypatch, process_id=process_id,
        extractor_fields=_legible_fields(h, nombre="JUAN PEREZ"), full_name="Juan Perez",
    )

    resp = h.handler(_s3_event(key), None)

    assert resp == {"processed": 1}
    documento.mark_validado.assert_called_once()
    documento.mark_rechazado.assert_not_called()
    h.upload_from_bytes.assert_called_once()
    # El evento final registrado debe ser el de validación.
    last_call = h.DocumentEvents.record.call_args_list[-1]
    assert last_call.kwargs["event_type"] == "documento_validado"


def test_marca_rechazado_ilegible_cuando_ocr_no_detecta_texto(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    key, documento = _wire(
        h, monkeypatch, process_id=process_id, extractor_fields=_ilegible_fields(h),
    )

    resp = h.handler(_s3_event(key), None)

    assert resp == {"processed": 1}
    documento.mark_rechazado.assert_called_once_with(reason="documento_ilegible")
    h.upload_from_bytes.assert_not_called()
    last_call = h.DocumentEvents.record.call_args_list[-1]
    assert last_call.kwargs["event_type"] == "documento_rechazado"
    assert last_call.kwargs["result"] == "documento_ilegible"


def test_marca_rechazado_no_corresponde_cuando_nombre_no_coincide(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    key, documento = _wire(
        h, monkeypatch, process_id=process_id,
        extractor_fields=_legible_fields(h, nombre="MARIA RODRIGUEZ"), full_name="Juan Perez",
    )

    resp = h.handler(_s3_event(key), None)

    assert resp == {"processed": 1}
    documento.mark_rechazado.assert_called_once_with(reason="no_corresponde")
    h.upload_from_bytes.assert_not_called()


def test_registra_evento_de_auditoria_en_cada_caso(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    key, _ = _wire(
        h, monkeypatch, process_id=process_id, extractor_fields=_ilegible_fields(h),
    )

    h.handler(_s3_event(key), None)

    # Al menos el evento de carga inicial + el de resultado final.
    assert h.DocumentEvents.record.call_count >= 2


def test_calcula_hash_sha256_solo_si_el_documento_queda_validado(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()

    key, documento = _wire(
        h, monkeypatch, process_id=process_id, extractor_fields=_ilegible_fields(h),
    )
    h.handler(_s3_event(key), None)
    mark_rechazado_kwargs = documento.mark_rechazado.call_args.kwargs
    assert "hash_sha256" not in mark_rechazado_kwargs

    key2, documento2 = _wire(
        h, monkeypatch, process_id=process_id,
        extractor_fields=_legible_fields(h, nombre="JUAN PEREZ"), full_name="Juan Perez",
    )
    h.handler(_s3_event(key2), None)
    mark_validado_kwargs = documento2.mark_validado.call_args.kwargs
    assert len(mark_validado_kwargs["hash_sha256"]) == 64  # sha256 hex digest


def test_es_idempotente_si_la_key_ya_fue_procesada(load_handler, monkeypatch):
    h = load_handler(__file__)
    process_id = uuid4()
    key = f"transactions/{process_id}/id_front/{uuid4()}.jpg"

    monkeypatch.setattr(
        h,
        "Documentos",
        MagicMock(
            get_by_s3_key=MagicMock(return_value=MagicMock()),  # ya existe
            register_from_s3=MagicMock(side_effect=AssertionError("no debe re-registrar")),
        ),
    )
    monkeypatch.setattr(h, "download_bytes", MagicMock(side_effect=AssertionError("no debe descargar")))
    monkeypatch.setattr(h.db_session, "commit", MagicMock())

    resp = h.handler(_s3_event(key), None)

    assert resp == {"processed": 1}
    h.Documentos.register_from_s3.assert_not_called()


def test_ignora_key_fuera_del_esquema_esperado(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(
        h,
        "Documentos",
        MagicMock(get_by_s3_key=MagicMock(side_effect=AssertionError)),
    )
    monkeypatch.setattr(h.db_session, "commit", MagicMock())

    resp = h.handler(_s3_event("random/stuff/here.jpg"), None)

    assert resp == {"processed": 1}
    h.Documentos.get_by_s3_key.assert_not_called()
