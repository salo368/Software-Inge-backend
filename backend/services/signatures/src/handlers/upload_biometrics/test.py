"""Unit tests for the signatures/upload_biometrics Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4


def _row(stage, created_at, **overrides):
    defaults = dict(id=str(uuid4()), stage=stage, created_at=created_at)
    defaults.update(overrides)
    return MagicMock(**defaults)


def _event(signature_id=None, biometric_type="ID_FRONT", content_type=None) -> dict:
    body = {}
    if signature_id is not None:
        body["signature_id"] = str(signature_id)
    if biometric_type is not None:
        body["biometric_type"] = biometric_type
    if content_type is not None:
        body["content_type"] = content_type
    return {"body": json.dumps(body)}


def test_upload_biometrics_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="BIOMETRICS", created_at=datetime.now(timezone.utc) - timedelta(minutes=2))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))
    presign_mock = MagicMock(return_value="https://presigned-upload-url")
    monkeypatch.setattr(h, "presign_upload", presign_mock)

    resp = h.handler(_event(row.id, "ID_FRONT"), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["upload_url"] == "https://presigned-upload-url"
    assert body["key"] == f"signatures/{row.id}/id_front.jpg"
    assert body["content_type"] == "image/jpeg"

    bucket, key, content_type = presign_mock.call_args.args
    assert key == f"signatures/{row.id}/id_front.jpg"
    assert content_type == "image/jpeg"


def test_upload_biometrics_png_content_type(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="BIOMETRICS", created_at=datetime.now(timezone.utc) - timedelta(minutes=2))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "presign_upload", MagicMock(return_value="https://x"))

    resp = h.handler(_event(row.id, "FACE", content_type="image/png"), None)

    body = json.loads(resp["body"])
    assert body["key"] == f"signatures/{row.id}/face.png"


def test_upload_biometrics_missing_signature_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(signature_id=None), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "signature_id is required"}


def test_upload_biometrics_invalid_signature_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event("not-a-uuid"), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid signature_id"}


def test_upload_biometrics_invalid_biometric_type_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(uuid4(), biometric_type="NOT_A_TYPE"), None)

    assert resp["statusCode"] == 400


def test_upload_biometrics_invalid_content_type_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(uuid4(), content_type="application/pdf"), None)

    assert resp["statusCode"] == 400


def test_upload_biometrics_not_found_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=None)))

    resp = h.handler(_event(uuid4()), None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "signature_not_found"}


def test_upload_biometrics_expired_returns_410(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="BIOMETRICS", created_at=datetime.now(timezone.utc) - timedelta(minutes=21))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "presign_upload", MagicMock(side_effect=AssertionError))

    resp = h.handler(_event(row.id), None)

    assert resp["statusCode"] == 410
    assert json.loads(resp["body"]) == {"error": "signature_expired"}


def test_upload_biometrics_wrong_stage_returns_409(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="FORM", created_at=datetime.now(timezone.utc) - timedelta(minutes=2))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "presign_upload", MagicMock(side_effect=AssertionError))

    resp = h.handler(_event(row.id), None)

    assert resp["statusCode"] == 409
    assert json.loads(resp["body"]) == {"error": "signature_not_in_biometrics_stage"}
