"""Unit tests for the signatures/set_otp Lambda."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4


def _row(stage, created_at, **overrides):
    defaults = dict(
        id=str(uuid4()), stage=stage, created_at=created_at,
        signatory="Juan Perez", email="juan@example.com",
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def _event(signature_id) -> dict:
    return {"body": json.dumps({} if signature_id is None else {"signature_id": str(signature_id)})}


def test_set_otp_happy_path_sends_email(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="OTP", created_at=datetime.now(timezone.utc) - timedelta(minutes=2))
    now = datetime.now(timezone.utc)
    updated = _row(stage="OTP", created_at=row.created_at, id=row.id,
                   signatory=row.signatory, email=row.email, otp_at=now)
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row), set_otp=MagicMock(return_value=updated))
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    send_email_mock = MagicMock(return_value=True)
    monkeypatch.setattr(h, "send_email", send_email_mock)

    resp = h.handler(_event(row.id), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["stage"] == "OTP"
    assert body["email_sent"] is True

    # the ORM gets a 6-digit code's SHA-256 hash, never the plaintext
    (sig_id, otp_hash), _ = signatures_mock.set_otp.call_args
    assert sig_id == UUID(row.id)
    assert len(otp_hash) == 64

    to, subject, html = send_email_mock.call_args.args
    assert to == row.email
    assert "verification code" in subject.lower()


def test_set_otp_resend_resets_tries_via_orm(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="OTP", created_at=datetime.now(timezone.utc) - timedelta(minutes=2), otp_tries=2)
    updated = _row(stage="OTP", created_at=row.created_at, id=row.id, otp_at=datetime.now(timezone.utc))
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row), set_otp=MagicMock(return_value=updated))
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    monkeypatch.setattr(h, "send_email", MagicMock(return_value=True))

    h.handler(_event(row.id), None)

    # resetting otp_tries is the ORM's job (set_otp always zeroes it);
    # this just proves the handler delegates to it rather than hand-rolling.
    signatures_mock.set_otp.assert_called_once()


def test_set_otp_mailer_failure_still_returns_200(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="OTP", created_at=datetime.now(timezone.utc) - timedelta(minutes=2))
    updated = _row(stage="OTP", created_at=row.created_at, id=row.id, otp_at=datetime.now(timezone.utc))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row), set_otp=MagicMock(return_value=updated)))
    monkeypatch.setattr(h, "send_email", MagicMock(return_value=False))

    resp = h.handler(_event(row.id), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["email_sent"] is False


def test_set_otp_missing_signature_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(None), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "signature_id is required"}


def test_set_otp_invalid_signature_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler({"body": json.dumps({"signature_id": "not-a-uuid"})}, None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid signature_id"}


def test_set_otp_not_found_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=None)))

    resp = h.handler(_event(uuid4()), None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "signature_not_found"}


def test_set_otp_expired_returns_410(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="OTP", created_at=datetime.now(timezone.utc) - timedelta(minutes=16))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row), set_otp=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(row.id), None)

    assert resp["statusCode"] == 410
    assert json.loads(resp["body"]) == {"error": "signature_expired"}


def test_set_otp_wrong_stage_returns_409(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(stage="SIGNATURE", created_at=datetime.now(timezone.utc) - timedelta(minutes=2))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row), set_otp=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(row.id), None)

    assert resp["statusCode"] == 409
    assert json.loads(resp["body"]) == {"error": "signature_not_in_otp_stage"}
