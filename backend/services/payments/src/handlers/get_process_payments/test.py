"""Unit tests for the payments/get_process_payments Lambda (backoffice, admin only)."""
from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID

_PID = "7077c70e-d8bf-4c8e-97ef-a7e0909949df"


def _patch_admin_auth(monkeypatch):
    monkeypatch.setattr(
        "libs.utils.auth.AdminBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None, admin_id="a-1"))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Admins", MagicMock(get_by_id=MagicMock(return_value=MagicMock(id="a-1"))))


def _event(query=None):
    return {"headers": {"Authorization": "Bearer adm"}, "queryStringParameters": query}


def _payment(n, amount, key):
    return MagicMock(id=UUID(int=n), amount=Decimal(amount), s3_file=key)


def test_get_process_payments_lists_receipts_and_total(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    rows = [_payment(1, "1500000.10", "payments/p/a.png"), _payment(2, "500000.20", None)]
    payments = MagicMock(list_by_process=MagicMock(return_value=rows))
    monkeypatch.setattr(h, "Payments", payments)
    presign = MagicMock(return_value="https://s3/receipt")
    monkeypatch.setattr(h, "presign_download", presign)

    resp = h.handler(_event({"process_id": _PID}), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["total_paid"] == 2000000.3
    assert [p["amount"] for p in body["payments"]] == [1500000.1, 500000.2]
    assert body["payments"][0]["receipt_url"] == "https://s3/receipt"
    assert body["payments"][1]["receipt_url"] is None
    presign.assert_called_once_with(h.BUCKET, "payments/p/a.png")
    payments.list_by_process.assert_called_once_with(UUID(_PID))


def test_get_process_payments_without_payments(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    monkeypatch.setattr(h, "Payments", MagicMock(list_by_process=MagicMock(return_value=[])))

    resp = h.handler(_event({"process_id": _PID}), None)

    assert json.loads(resp["body"]) == {"payments": [], "total_paid": 0.0}


def test_get_process_payments_invalid_process_id(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    payments = MagicMock()
    monkeypatch.setattr(h, "Payments", payments)

    resp = h.handler(_event({"process_id": "nope"}), None)

    assert resp["statusCode"] == 400
    payments.list_by_process.assert_not_called()


def test_get_process_payments_requires_admin_token(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr("libs.utils.auth.AdminBearerTokens", MagicMock(get_by_hash=MagicMock(return_value=None)))
    payments = MagicMock()
    monkeypatch.setattr(h, "Payments", payments)

    resp = h.handler(_event({"process_id": _PID}), None)

    assert resp["statusCode"] == 401
    payments.list_by_process.assert_not_called()
