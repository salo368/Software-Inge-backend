"""Unit tests for the signatures notify_signed worker."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4


def _row(**overrides):
    defaults = dict(
        id=str(uuid4()),
        stage="SIGNED",
        signed_s3_key="signatures/x/signed.pdf",
        signatory="Juan Perez",
        email="juan@example.com",
        signed_at=datetime(2026, 11, 3, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def test_notify_signed_happy_path_sends_link(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row()
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "presign_download", MagicMock(return_value="https://signed-url"))
    send_email_mock = MagicMock(return_value=True)
    monkeypatch.setattr(h, "send_email", send_email_mock)

    result = h.handler({"signature_id": row.id}, None)

    assert result == {"ok": True, "signature_id": row.id}
    to, subject, html = send_email_mock.call_args.args
    assert to == row.email
    assert "https://signed-url" in html


def test_notify_signed_missing_signature_id(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    result = h.handler({}, None)

    assert result == {"ok": False, "error": "missing_signature_id"}


def test_notify_signed_not_found(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=None)))

    result = h.handler({"signature_id": str(uuid4())}, None)

    assert result == {"ok": False, "error": "signature_not_found"}


def test_notify_signed_wrong_stage_is_skipped(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="SIGNING", signed_s3_key=None)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "send_email", MagicMock(side_effect=AssertionError))

    result = h.handler({"signature_id": row.id}, None)

    assert result == {"ok": False, "skipped": True, "stage": "SIGNING"}


def test_notify_signed_no_email_on_file(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(email=None)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "send_email", MagicMock(side_effect=AssertionError))

    result = h.handler({"signature_id": row.id}, None)

    assert result == {"ok": False, "error": "no_email"}


def test_notify_signed_mailer_failure_is_reported(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row()
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "presign_download", MagicMock(return_value="https://signed-url"))
    monkeypatch.setattr(h, "send_email", MagicMock(return_value=False))

    result = h.handler({"signature_id": row.id}, None)

    assert result == {"ok": False, "signature_id": row.id}
