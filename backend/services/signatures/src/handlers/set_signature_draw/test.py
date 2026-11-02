"""Unit tests for the signatures/set_signature_draw Lambda."""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4

_VALID_BYTES = b"x" * 2048
_TOO_SMALL_BYTES = b"x" * 10
_TOO_LARGE_BYTES = b"x" * (2 * 1024 * 1024 + 1)


def _row(stage, created_at, **overrides):
    defaults = dict(id=str(uuid4()), stage=stage, created_at=created_at, draw_s3_key=None)
    defaults.update(overrides)
    return MagicMock(**defaults)


def _event(signature_id=None, data=_VALID_BYTES, *, base64_encoded=True) -> dict:
    event = {
        "queryStringParameters": {} if signature_id is None else {"signature_id": str(signature_id)},
    }
    if base64_encoded:
        event.update(body=base64.b64encode(data).decode(), isBase64Encoded=True)
    else:
        event.update(body=data.decode("latin-1"), isBase64Encoded=False)
    return event


def test_set_signature_draw_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="SIGNATURE", created_at=datetime.now(timezone.utc) - timedelta(minutes=2))
    upload_mock = MagicMock()
    monkeypatch.setattr(h, "upload_from_bytes", upload_mock)
    signatures_mock = MagicMock(
        get_by_id=MagicMock(return_value=row),
        set_draw_key=MagicMock(return_value=_row(
            stage="OTP", created_at=row.created_at, id=row.id,
            draw_s3_key=f"signatures/{row.id}/draw.bin",
        )),
    )
    monkeypatch.setattr(h, "Signatures", signatures_mock)

    resp = h.handler(_event(row.id), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["stage"] == "OTP"
    assert body["draw_s3_key"] == f"signatures/{row.id}/draw.bin"

    bucket, key, data = upload_mock.call_args.args
    assert key == f"signatures/{row.id}/draw.bin"
    assert data == _VALID_BYTES
    assert upload_mock.call_args.kwargs["content_type"] == "application/octet-stream"

    signatures_mock.set_draw_key.assert_called_once_with(UUID(row.id), f"signatures/{row.id}/draw.bin")


def test_set_signature_draw_raw_body(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="SIGNATURE", created_at=datetime.now(timezone.utc) - timedelta(minutes=2))
    upload_mock = MagicMock()
    monkeypatch.setattr(h, "upload_from_bytes", upload_mock)
    monkeypatch.setattr(h, "Signatures", MagicMock(
        get_by_id=MagicMock(return_value=row),
        set_draw_key=MagicMock(return_value=MagicMock()),
    ))

    h.handler(_event(row.id, base64_encoded=False), None)

    bucket, key, data = upload_mock.call_args.args
    assert data == _VALID_BYTES


def test_set_signature_draw_missing_signature_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(signature_id=None), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "signature_id is required"}


def test_set_signature_draw_invalid_signature_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event("not-a-uuid"), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid signature_id"}


def test_set_signature_draw_empty_returns_422(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(uuid4(), data=_TOO_SMALL_BYTES), None)

    assert resp["statusCode"] == 422
    assert json.loads(resp["body"]) == {"error": "draw_invalid_empty"}


def test_set_signature_draw_too_large_returns_413(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(uuid4(), data=_TOO_LARGE_BYTES), None)

    assert resp["statusCode"] == 413
    assert json.loads(resp["body"]) == {"error": "draw_invalid_too_large"}


def test_set_signature_draw_not_found_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=None)))

    resp = h.handler(_event(uuid4()), None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "signature_not_found"}


def test_set_signature_draw_expired_returns_410(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="SIGNATURE", created_at=datetime.now(timezone.utc) - timedelta(minutes=21))
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))

    resp = h.handler(_event(row.id), None)

    assert resp["statusCode"] == 410
    assert json.loads(resp["body"]) == {"error": "signature_expired"}


def test_set_signature_draw_wrong_stage_returns_409(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="BIOMETRICS", created_at=datetime.now(timezone.utc) - timedelta(minutes=2))
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))

    resp = h.handler(_event(row.id), None)

    assert resp["statusCode"] == 409
    assert json.loads(resp["body"]) == {"error": "signature_not_in_signature_stage"}
