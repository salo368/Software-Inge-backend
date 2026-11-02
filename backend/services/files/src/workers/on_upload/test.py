"""Unit tests for the files/on_upload S3 worker."""
from __future__ import annotations

from uuid import uuid4
from unittest.mock import MagicMock


def _s3_event(key: str, bucket: str = "cdts-test-files") -> dict:
    return {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}


def test_on_upload_registers_new_file(load_handler, monkeypatch):
    h = load_handler(__file__)

    process_id = uuid4()
    file_uuid = uuid4()
    key = f"processes/{process_id}/tax_declaration/{file_uuid}.pdf"

    monkeypatch.setattr(h, "Files", MagicMock(create=MagicMock()))
    monkeypatch.setattr(
        h,
        "head_object",
        MagicMock(return_value={
            "ContentLength": 123,
            "ContentType": "application/pdf",
            "Metadata": {"original-name": "declaraci%C3%B3n%20renta.pdf"},
        }),
    )
    monkeypatch.setattr(h.db_session, "commit", MagicMock())

    resp = h.handler(_s3_event(key), None)

    assert resp == {"processed": 1}
    h.Files.create.assert_called_once()
    kwargs = h.Files.create.call_args.kwargs
    assert kwargs["process_id"] == process_id
    assert kwargs["file_type"] == "tax_declaration"
    assert kwargs["s3_key"] == key
    assert kwargs["original_name"] == "declaración renta.pdf"  # unquoted
    assert kwargs["size_bytes"] == 123
    assert kwargs["content_type"] == "application/pdf"


def test_on_upload_ignores_key_outside_processes_prefix(load_handler, monkeypatch):
    """A key that does not match the processes/{uuid}/{type}/{name} shape must
    be silently ignored (log-only)."""
    h = load_handler(__file__)

    monkeypatch.setattr(h, "Files", MagicMock(create=MagicMock(side_effect=AssertionError("should not run"))))
    monkeypatch.setattr(h, "head_object", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h.db_session, "commit", MagicMock())

    resp = h.handler(_s3_event("random/stuff/here.pdf"), None)

    assert resp == {"processed": 1}
    h.Files.create.assert_not_called()


def test_on_upload_duplicate_delivery_is_logged_not_raised(load_handler, monkeypatch):
    """S3 only guarantees at-least-once delivery. A duplicate notification for
    an already-registered key hits the `s3_key` UNIQUE constraint; the
    per-record try/except in `handler` must swallow that and keep going
    instead of failing the whole batch."""
    h = load_handler(__file__)

    key = f"processes/{uuid4()}/tax_declaration/{uuid4()}.pdf"
    monkeypatch.setattr(
        h, "Files", MagicMock(create=MagicMock(side_effect=Exception("duplicate key value violates unique constraint")))
    )
    monkeypatch.setattr(
        h,
        "head_object",
        MagicMock(return_value={"ContentLength": 1, "ContentType": "application/pdf", "Metadata": {}}),
    )
    monkeypatch.setattr(h.db_session, "commit", MagicMock())

    resp = h.handler(_s3_event(key), None)

    assert resp == {"processed": 1}
    h.Files.create.assert_called_once()
