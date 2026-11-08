"""Unit tests for the payments/list_process_payments internal Lambda."""
from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID

_PID = "7077c70e-d8bf-4c8e-97ef-a7e0909949df"


def _event(process_id) -> dict:
    return {"body": json.dumps({"process_id": process_id})}


def test_list_process_payments_returns_exact_amounts(load_handler, monkeypatch):
    h = load_handler(__file__)
    rows = [
        MagicMock(id="p1", amount=Decimal("1000000.10"), s3_file="payments/a.png"),
        MagicMock(id="p2", amount=Decimal("0.20"), s3_file=None),
    ]
    payments = MagicMock(list_by_process=MagicMock(return_value=rows))
    monkeypatch.setattr(h, "Payments", payments)

    resp = h.handler(_event(_PID), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"payments": [
        {"id": "p1", "amount": "1000000.10", "s3_file": "payments/a.png"},
        {"id": "p2", "amount": "0.20", "s3_file": None},
    ]}
    payments.list_by_process.assert_called_once_with(UUID(_PID))


def test_list_process_payments_empty(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Payments", MagicMock(list_by_process=MagicMock(return_value=[])))

    resp = h.handler(_event(_PID), None)

    assert json.loads(resp["body"]) == {"payments": []}


def test_list_process_payments_invalid_process_id(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Payments", MagicMock(list_by_process=MagicMock(side_effect=AssertionError)))

    for event in (_event("nope"), {"body": "{}"}):
        resp = h.handler(event, None)

        assert resp["statusCode"] == 400
