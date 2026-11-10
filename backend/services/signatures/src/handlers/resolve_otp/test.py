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


def test_resolve_otp_correct_code_starts_signing(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(
        stage="OTP", created_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        otp_at=datetime.now(timezone.utc) - timedelta(seconds=30), otp_hash=_hash(_CODE),
    )
    signatures_mock = MagicMock(
        get_by_id=MagicMock(return_value=row),
        start_signing=MagicMock(return_value=_row(stage="SIGNING", created_at=row.created_at, id=row.id)),
    )
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    send_message_mock = MagicMock()
    monkeypatch.setattr(h, "send_message", send_message_mock)
    invoke_async_mock = MagicMock()
    monkeypatch.setattr(h, "invoke_async", invoke_async_mock)

    event = _event(row.id, _CODE)
    event["headers"] = {"user-agent": "pytest-agent", "accept-language": "es-CO"}
    event["requestContext"] = {"http": {"sourceIp": "203.0.113.5"}}

    resp = h.handler(event, None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["stage"] == "SIGNING"
    signatures_mock.register_failed_otp_attempt.assert_not_called()

    (sig_id, signing_data), _ = signatures_mock.start_signing.call_args
    assert sig_id == UUID(row.id)
    assert signing_data["ip"] == "203.0.113.5"
    assert signing_data["user_agent"] == "pytest-agent"
    assert signing_data["accept_language"] == "es-CO"
    assert "resolved_at" in signing_data

    queue_url, body = send_message_mock.call_args.args
    assert queue_url == h.SIGNING_TIMEOUT_QUEUE_URL
    assert json.loads(body) == {"signature_id": row.id}
    assert send_message_mock.call_args.kwargs["delay_seconds"] == int(h.SIGNING_TIMEOUT.total_seconds())

    invoke_async_mock.assert_called_once_with("sign_doc", {"signature_id": row.id})


def test_resolve_otp_sign_doc_invoke_failure_returns_502_and_rolls_back(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(
        stage="OTP", created_at=datetime.now(timezone.utc) - timedelta(minutes=2),
        otp_at=datetime.now(timezone.utc) - timedelta(seconds=30), otp_hash=_hash(_CODE),
    )
    signatures_mock = MagicMock(
        get_by_id=MagicMock(return_value=row),
        start_signing=MagicMock(return_value=_row(stage="SIGNING", created_at=row.created_at, id=row.id)),
    )
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    monkeypatch.setattr(h, "send_message", MagicMock())
    monkeypatch.setattr(
        h, "invoke_async", MagicMock(side_effect=h.LambdaInvokeError("sign_doc", "boto_error", "boom"))
    )

    resp = h.handler(_event(row.id, _CODE), None)

    assert resp["statusCode"] == 502
    assert json.loads(resp["body"]) == {"error": "sign_doc_unavailable"}


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

    # Regression guard: handle_exceptions rolls back the whole transaction
    # on a `raise HandledError`, which would silently undo mark_failed()'s
    # write along with it. The handler must return the 429 normally (not
    # raise) so the wrapper commits instead of rolling back.
    import libs.core.responses as responses_module
    fake_db_session = MagicMock()
    monkeypatch.setattr(responses_module, "db_session", fake_db_session)
    notify_mock = MagicMock()
    monkeypatch.setattr(h, "notify_terminal_state", notify_mock)

    resp = h.handler(_event(row.id, "000000"), None)

    assert resp["statusCode"] == 429
    assert json.loads(resp["body"]) == {"error": "otp_max_attempts"}
    signatures_mock.mark_failed.assert_called_once_with(UUID(row.id))
    fake_db_session.commit.assert_called_once()
    fake_db_session.rollback.assert_not_called()
    notify_mock.assert_called_once_with(UUID(row.id), "FAILED")


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
