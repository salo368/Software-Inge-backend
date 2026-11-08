"""Unit tests for the files/on_upload S3 worker."""
from __future__ import annotations

from uuid import uuid4
from unittest.mock import MagicMock


def _s3_event(key: str, bucket: str = "cdts-test-files") -> dict:
    return {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}


def _head(**metadata) -> dict:
    return {"ContentLength": 123, "ContentType": "application/pdf", "Metadata": metadata}


def _setup(h, monkeypatch, head, create=None):
    monkeypatch.setattr(h, "Files", MagicMock(create=create or MagicMock()))
    monkeypatch.setattr(h, "head_object", MagicMock(return_value=head))
    monkeypatch.setattr(h.db_session, "commit", MagicMock())


def test_on_upload_registers_new_file_from_metadata(load_handler, monkeypatch):
    h = load_handler(__file__)

    process_id = uuid4()
    # The key deliberately does not encode the process or type: only
    # the metadata is trusted.
    key = f"processes/other/path/{uuid4()}.pdf"
    _setup(h, monkeypatch, _head(**{
        "process-id": str(process_id),
        "file-type": "TAX_DECLARATION",
        "original-name": "declaraci%C3%B3n%20renta.pdf",
    }))

    resp = h.handler(_s3_event(key), None)

    assert resp == {"processed": 1}
    h.Files.create.assert_called_once()
    kwargs = h.Files.create.call_args.kwargs
    assert kwargs["process_id"] == process_id
    assert kwargs["file_type"] == "TAX_DECLARATION"
    assert kwargs["s3_key"] == key
    assert kwargs["original_name"] == "declaración renta.pdf"  # unquoted
    assert kwargs["size_bytes"] == 123
    assert kwargs["content_type"] == "application/pdf"


def test_on_upload_without_original_name_stores_none(load_handler, monkeypatch):
    h = load_handler(__file__)
    _setup(h, monkeypatch, _head(**{"process-id": str(uuid4()), "file-type": "RUT"}))

    h.handler(_s3_event(f"processes/{uuid4()}/RUT/{uuid4()}.pdf"), None)

    assert h.Files.create.call_args.kwargs["original_name"] is None


def test_on_upload_ignores_object_without_process_id(load_handler, monkeypatch):
    h = load_handler(__file__)
    _setup(h, monkeypatch, _head(**{"file-type": "RUT"}),
           create=MagicMock(side_effect=AssertionError("should not run")))

    resp = h.handler(_s3_event(f"processes/{uuid4()}/RUT/{uuid4()}.pdf"), None)

    assert resp == {"processed": 1}
    h.Files.create.assert_not_called()


def test_on_upload_ignores_invalid_process_id(load_handler, monkeypatch):
    h = load_handler(__file__)
    _setup(h, monkeypatch, _head(**{"process-id": "nope", "file-type": "RUT"}))

    h.handler(_s3_event("processes/x/RUT/y.pdf"), None)

    h.Files.create.assert_not_called()


def test_on_upload_ignores_unknown_file_type(load_handler, monkeypatch):
    h = load_handler(__file__)
    _setup(h, monkeypatch, _head(**{"process-id": str(uuid4()), "file-type": "NOT_A_TYPE"}))

    h.handler(_s3_event("processes/x/NOT_A_TYPE/y.pdf"), None)

    h.Files.create.assert_not_called()


def test_on_upload_duplicate_delivery_is_logged_not_raised(load_handler, monkeypatch):
    """S3 only guarantees at-least-once delivery. A duplicate notification for
    an already-registered key hits the `s3_key` UNIQUE constraint; the
    per-record try/except in `handler` must swallow that and keep going
    instead of failing the whole batch."""
    h = load_handler(__file__)
    _setup(
        h, monkeypatch,
        _head(**{"process-id": str(uuid4()), "file-type": "TAX_DECLARATION"}),
        create=MagicMock(side_effect=Exception("duplicate key value violates unique constraint")),
    )

    resp = h.handler(_s3_event(f"processes/{uuid4()}/TAX_DECLARATION/{uuid4()}.pdf"), None)

    assert resp == {"processed": 1}
    h.Files.create.assert_called_once()
