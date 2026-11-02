"""Unit tests for the signatures/set_biometrics Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4


def _row(stage, created_at, **overrides):
    defaults = dict(id=str(uuid4()), stage=stage, created_at=created_at)
    defaults.update(overrides)
    return MagicMock(**defaults)


def _event(signature_id=None, biometric_type="ID_FRONT", s3_key=None) -> dict:
    body = {}
    if signature_id is not None:
        body["signature_id"] = str(signature_id)
    if biometric_type is not None:
        body["biometric_type"] = biometric_type
    if s3_key is not None:
        body["s3_key"] = s3_key
    return {"body": json.dumps(body)}


def _mock_analyzers(h, monkeypatch, **by_type):
    """Replaces h._ANALYZERS wholesale (via monkeypatch, so it's auto-reverted
    and doesn't leak into other tests through the cached handler module);
    `by_type` maps e.g. ID_FRONT=(True, 'ok')."""
    mocks = {biometric_type: MagicMock(return_value=result) for biometric_type, result in by_type.items()}
    monkeypatch.setattr(h, "_ANALYZERS", mocks)


def test_set_biometrics_valid_persists_key(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="BIOMETRICS", created_at=datetime.now(timezone.utc) - timedelta(minutes=2))
    key = f"signatures/{row.id}/id_front.jpg"
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row))
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    _mock_analyzers(h, monkeypatch, ID_FRONT=(True, "ok"))

    resp = h.handler(_event(row.id, "ID_FRONT", key), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"is_valid": True, "reason": "ok"}
    signatures_mock.set_biometric_key.assert_called_once_with(UUID(row.id), "ID_FRONT", key)


def test_set_biometrics_invalid_does_not_persist(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="BIOMETRICS", created_at=datetime.now(timezone.utc) - timedelta(minutes=2))
    key = f"signatures/{row.id}/face.jpg"
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row))
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    _mock_analyzers(h, monkeypatch, FACE=(False, "no_face_detected"))

    resp = h.handler(_event(row.id, "FACE", key), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"is_valid": False, "reason": "no_face_detected"}
    signatures_mock.set_biometric_key.assert_not_called()


def test_set_biometrics_missing_signature_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(signature_id=None, s3_key="signatures/x/id_front.jpg"), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "signature_id is required"}


def test_set_biometrics_invalid_signature_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event("not-a-uuid", s3_key="signatures/x/id_front.jpg"), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid signature_id"}


def test_set_biometrics_invalid_biometric_type_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(uuid4(), biometric_type="NOT_A_TYPE", s3_key="signatures/x/y.jpg"), None)

    assert resp["statusCode"] == 400


def test_set_biometrics_missing_s3_key_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(uuid4(), s3_key=None), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "s3_key is required"}


def test_set_biometrics_s3_key_cross_signature_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    sig_id = uuid4()
    other_id = uuid4()
    resp = h.handler(_event(sig_id, s3_key=f"signatures/{other_id}/id_front.jpg"), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "s3_key does not belong to this signature"}


def test_set_biometrics_not_found_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=None)))

    sig_id = uuid4()
    resp = h.handler(_event(sig_id, s3_key=f"signatures/{sig_id}/id_front.jpg"), None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "signature_not_found"}


def test_set_biometrics_expired_returns_410(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="BIOMETRICS", created_at=datetime.now(timezone.utc) - timedelta(minutes=21))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))
    _mock_analyzers(h, monkeypatch, ID_FRONT=(True, "ok"))

    resp = h.handler(_event(row.id, s3_key=f"signatures/{row.id}/id_front.jpg"), None)

    assert resp["statusCode"] == 410
    assert json.loads(resp["body"]) == {"error": "signature_expired"}


def test_set_biometrics_wrong_stage_returns_409(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="FORM", created_at=datetime.now(timezone.utc) - timedelta(minutes=2))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))
    _mock_analyzers(h, monkeypatch, ID_FRONT=(True, "ok"))

    resp = h.handler(_event(row.id, s3_key=f"signatures/{row.id}/id_front.jpg"), None)

    assert resp["statusCode"] == 409
    assert json.loads(resp["body"]) == {"error": "signature_not_in_biometrics_stage"}
