"""Unit tests for the payments/create_payment Lambda."""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID

_PID = "7077c70e-d8bf-4c8e-97ef-a7e0909949df"
_KEY = f"payments/{_PID}/0f11b02e-c128-4caf-a76c-7867e82d1165.png"


def _event(body: dict, headers: dict | None = None) -> dict:
    return {
        "headers": headers if headers is not None else {"Authorization": "Bearer tok"},
        "body": json.dumps(body),
    }


def _patch_auth(monkeypatch):
    monkeypatch.setattr(
        "libs.utils.auth.BearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Users", MagicMock(get_by_id=MagicMock(return_value=MagicMock(id="u-1"))))


def _patch(h, monkeypatch, processes):
    lookup = sys.modules[h.get_payable_process.__module__]
    monkeypatch.setattr(
        lookup, "invoke_sync",
        MagicMock(return_value={"statusCode": 200, "body": json.dumps({"processes": processes})}),
    )
    payments = MagicMock()
    payments.create.return_value = MagicMock(
        id="pay-1", process_id=UUID(_PID), amount=Decimal("1500000.00"), s3_file=_KEY,
    )
    monkeypatch.setattr(h, "Payments", payments)
    return payments


def test_create_payment_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    payments = _patch(h, monkeypatch, [{"id": _PID, "stage": "PAYMENT"}])

    resp = h.handler(_event({"process_id": _PID, "s3_key": _KEY, "amount": "1500000"}), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"id": "pay-1", "process_id": _PID, "amount": 1500000.0, "s3_file": _KEY}
    payments.create.assert_called_once_with(process_id=UUID(_PID), amount=Decimal("1500000"), s3_file=_KEY)


def test_create_payment_invalid_process_id(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    payments = _patch(h, monkeypatch, [])

    resp = h.handler(_event({"process_id": "nope", "s3_key": _KEY, "amount": "1"}), None)

    assert resp["statusCode"] == 400
    payments.create.assert_not_called()


def test_create_payment_missing_s3_key(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    payments = _patch(h, monkeypatch, [{"id": _PID, "stage": "PAYMENT"}])

    resp = h.handler(_event({"process_id": _PID, "amount": "1"}), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "s3_key is required"}
    payments.create.assert_not_called()


def test_create_payment_s3_key_of_other_process(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    payments = _patch(h, monkeypatch, [{"id": _PID, "stage": "PAYMENT"}])

    for key in ("payments/00000000-0000-0000-0000-000000000000/x.png", f"processes/{_PID}/BANK_CERT/x.pdf"):
        resp = h.handler(_event({"process_id": _PID, "s3_key": key, "amount": "1"}), None)

        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "s3_key does not belong to this process"}
    payments.create.assert_not_called()


def test_create_payment_invalid_amounts(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    payments = _patch(h, monkeypatch, [{"id": _PID, "stage": "PAYMENT"}])

    for amount in (None, "abc", "0", "-5", "NaN", "Infinity"):
        resp = h.handler(_event({"process_id": _PID, "s3_key": _KEY, "amount": amount}), None)

        assert resp["statusCode"] == 400, amount
        assert json.loads(resp["body"]) == {"error": "invalid_amount"}
    payments.create.assert_not_called()


def test_create_payment_process_of_other_user_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    payments = _patch(h, monkeypatch, [])

    resp = h.handler(_event({"process_id": _PID, "s3_key": _KEY, "amount": "1"}), None)

    assert resp["statusCode"] == 404
    payments.create.assert_not_called()


def test_create_payment_process_not_in_payment_returns_409(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    payments = _patch(h, monkeypatch, [{"id": _PID, "stage": "REVIEW"}])

    resp = h.handler(_event({"process_id": _PID, "s3_key": _KEY, "amount": "1"}), None)

    assert resp["statusCode"] == 409
    payments.create.assert_not_called()


def test_create_payment_propagates_auth_error_from_processes(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    lookup = sys.modules[h.get_payable_process.__module__]
    monkeypatch.setattr(
        lookup, "invoke_sync",
        MagicMock(return_value={"statusCode": 401, "body": json.dumps({"error": "invalid_or_expired_token"})}),
    )
    monkeypatch.setattr(h, "Payments", MagicMock())

    resp = h.handler(_event({"process_id": _PID, "s3_key": _KEY, "amount": "1"}), None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "invalid_or_expired_token"}


def test_create_payment_requires_auth(load_handler):
    h = load_handler(__file__)

    resp = h.handler(_event({"process_id": _PID}, headers={}), None)

    assert resp["statusCode"] == 401
