"""Unit tests for the signatures/resolve_otp Lambda."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4

_CODE = "123456"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _row(stage, created_at, otp_at=None, otp_hash=None, otp_tries=0, **overrides):
    defaults = dict(
        id=str(uuid4()), stage=stage, created_at=created_at,
        otp_at=otp_at, otp_hash=otp_hash, otp_tries=otp_tries,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def _event(signature_id=None, code=_CODE) -> dict:
    body = {}
    if signature_id is not None:
        body["signature_id"] = str(signature_id)
    if code is not None:
        body["code"] = code
    return {"body": json.dumps(body)}


def test_resolve_otp_correct_code_marks_signed(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(
        stage="OTP", created_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        otp_at=datetime.now(timezone.utc) - timedelta(seconds=30), otp_hash=_hash(_CODE),
    )
    signatures_mock = MagicMock(
        get_by_id=MagicMock(return_value=row),
        mark_signed=MagicMock(return_value=_row(stage="SIGNED", created_at=row.created_at, id=row.id)),
    )
    monkeypatch.setattr(h, "Signatures", signatures_mock)

    resp = h.handler(_event(row.id, _CODE), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["stage"] == "SIGNED"
    signatures_mock.mark_signed.assert_called_once_with(UUID(row.id))
    signatures_mock.register_failed_otp_attempt.assert_not_called()


def test_resolve_otp_wrong_code_returns_401_with_attempts_left(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(
        stage="OTP", created_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        otp_at=datetime.now(timezone.utc) - timedelta(seconds=30), otp_hash=_hash(_CODE),
    )
    updated = _row(stage="OTP", created_at=row.created_at, id=row.id, otp_tries=1)
    signatures_mock = MagicMock(
        get_by_id=MagicMock(return_value=row),
        register_failed_otp_attempt=MagicMock(return_value=updated),
        mark_failed=MagicMock(side_effect=AssertionError),
    )
    monkeypatch.setattr(h, "Signatures", signatures_mock)

    resp = h.handler(_event(row.id, "000000"), None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "otp_invalid", "attempts_left": 2}


def test_resolve_otp_third_wrong_attempt_marks_failed(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(
        stage="OTP", created_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        otp_at=datetime.now(timezone.utc) - timedelta(seconds=30), otp_hash=_hash(_CODE),
        otp_tries=2,
    )
    updated = _row(stage="OTP", created_at=row.created_at, id=row.id, otp_tries=3)
    signatures_mock = MagicMock(
        get_by_id=MagicMock(return_value=row),
        register_failed_otp_attempt=MagicMock(return_value=updated),
        mark_failed=MagicMock(return_value=_row(stage="FAILED", created_at=row.created_at, id=row.id)),
    )
    monkeypatch.setattr(h, "Signatures", signatures_mock)

    resp = h.handler(_event(row.id, "000000"), None)

    assert resp["statusCode"] == 429
    assert json.loads(resp["body"]) == {"error": "otp_max_attempts"}
    signatures_mock.mark_failed.assert_called_once_with(UUID(row.id))


def test_resolve_otp_missing_signature_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(None, _CODE), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "signature_id is required"}


def test_resolve_otp_invalid_signature_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event("not-a-uuid", _CODE), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid signature_id"}


def test_resolve_otp_missing_code_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(uuid4(), code=None), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "code is required"}


def test_resolve_otp_invalid_code_format_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(uuid4(), code="12ab56"), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid_code_format"}


def test_resolve_otp_not_found_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=None)))

    resp = h.handler(_event(uuid4(), _CODE), None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "signature_not_found"}


def test_resolve_otp_signing_window_expired_returns_410(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="OTP", created_at=datetime.now(timezone.utc) - timedelta(minutes=16))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))

    resp = h.handler(_event(row.id, _CODE), None)

    assert resp["statusCode"] == 410
    assert json.loads(resp["body"]) == {"error": "signature_expired"}


def test_resolve_otp_wrong_stage_returns_409(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="SIGNATURE", created_at=datetime.now(timezone.utc) - timedelta(minutes=2))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))

    resp = h.handler(_event(row.id, _CODE), None)

    assert resp["statusCode"] == 409
    assert json.loads(resp["body"]) == {"error": "signature_not_in_otp_stage"}


def test_resolve_otp_not_requested_returns_409(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="OTP", created_at=datetime.now(timezone.utc) - timedelta(minutes=2), otp_hash=None, otp_at=None)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))

    resp = h.handler(_event(row.id, _CODE), None)

    assert resp["statusCode"] == 409
    assert json.loads(resp["body"]) == {"error": "otp_not_requested"}


def test_resolve_otp_code_expired_returns_401(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(
        stage="OTP", created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        otp_at=datetime.now(timezone.utc) - timedelta(minutes=3), otp_hash=_hash(_CODE),
    )
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))

    resp = h.handler(_event(row.id, _CODE), None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "otp_expired"}
