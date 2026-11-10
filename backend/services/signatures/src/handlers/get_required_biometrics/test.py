"""Unit tests for the signatures/get_required_biometrics Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4


def _row(stage, created_at, id_front_s3_key=None, id_back_s3_key=None, id_face_s3_key=None, **overrides):
    defaults = dict(
        id=str(uuid4()),
        stage=stage,
        created_at=created_at,
        id_front_s3_key=id_front_s3_key,
        id_back_s3_key=id_back_s3_key,
        id_face_s3_key=id_face_s3_key,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def _event(signature_id) -> dict:
    return {"queryStringParameters": {} if signature_id is None else {"signature_id": str(signature_id)}}


def test_get_required_biometrics_none_uploaded(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="BIOMETRICS", created_at=datetime.now(timezone.utc) - timedelta(minutes=2))
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row))
    monkeypatch.setattr(h, "Signatures", signatures_mock)

    resp = h.handler(_event(row.id), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"ID_FRONT": False, "ID_BACK": False, "FACE": False}
    signatures_mock.advance_to_signature_stage.assert_not_called()


def test_get_required_biometrics_partial(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(
        stage="BIOMETRICS", created_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        id_front_s3_key="signatures/x/id_front.jpg",
    )
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row))
    monkeypatch.setattr(h, "Signatures", signatures_mock)

    resp = h.handler(_event(row.id), None)

    assert json.loads(resp["body"]) == {"ID_FRONT": True, "ID_BACK": False, "FACE": False}
    signatures_mock.advance_to_signature_stage.assert_not_called()


def test_get_required_biometrics_all_present_advances_stage(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(
        stage="BIOMETRICS", created_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        id_front_s3_key="signatures/x/id_front.jpg",
        id_back_s3_key="signatures/x/id_back.jpg",
        id_face_s3_key="signatures/x/face.jpg",
    )
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row))
    monkeypatch.setattr(h, "Signatures", signatures_mock)

    resp = h.handler(_event(row.id), None)

    assert json.loads(resp["body"]) == {"ID_FRONT": True, "ID_BACK": True, "FACE": True}
    signatures_mock.advance_to_signature_stage.assert_called_once_with(UUID(row.id))


def test_get_required_biometrics_all_present_but_wrong_stage_does_not_advance(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(
        stage="SIGNATURE", created_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        id_front_s3_key="signatures/x/id_front.jpg",
        id_back_s3_key="signatures/x/id_back.jpg",
        id_face_s3_key="signatures/x/face.jpg",
    )
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row))
    monkeypatch.setattr(h, "Signatures", signatures_mock)

    h.handler(_event(row.id), None)

    signatures_mock.advance_to_signature_stage.assert_not_called()


def test_get_required_biometrics_missing_signature_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(None), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "signature_id is required"}


def test_get_required_biometrics_invalid_signature_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler({"queryStringParameters": {"signature_id": "not-a-uuid"}}, None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid signature_id"}


def test_get_required_biometrics_not_found_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=None)))

    resp = h.handler(_event(uuid4()), None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "signature_not_found"}


def test_get_required_biometrics_expired_returns_410(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="BIOMETRICS", created_at=datetime.now(timezone.utc) - timedelta(minutes=21))
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row))
    monkeypatch.setattr(h, "Signatures", signatures_mock)

    resp = h.handler(_event(row.id), None)

    assert resp["statusCode"] == 410
    assert json.loads(resp["body"]) == {"error": "signature_expired"}
    signatures_mock.advance_to_signature_stage.assert_not_called()
