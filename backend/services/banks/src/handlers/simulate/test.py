"""Unit tests for the banks/simulate Lambda."""
from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock


def _event(body: dict | None) -> dict:
    return {"body": json.dumps(body) if body is not None else None}


def test_simulate_happy_path_sorts_by_rate_desc(load_handler, monkeypatch):
    h = load_handler(__file__)

    b1 = MagicMock(id=1, public_dict=MagicMock(return_value={"id": 1, "name": "Bank A"}))
    b2 = MagicMock(id=2, public_dict=MagicMock(return_value={"id": 2, "name": "Bank B"}))
    b3 = MagicMock(id=3, public_dict=MagicMock(return_value={"id": 3, "name": "Bank C"}))
    monkeypatch.setattr(h, "Banks", MagicMock(list_active=MagicMock(return_value=[b1, b2, b3])))

    # b3 has no bracket for this amount and must be dropped from the result.
    monkeypatch.setattr(
        h,
        "BankRates",
        MagicMock(best_per_bank=MagicMock(return_value={1: Decimal("10.0"), 2: Decimal("12.5")})),
    )

    resp = h.handler(_event({"amount": "1000000", "term_days": 180}), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["amount"] == 1000000
    assert body["term_days"] == 180
    # Highest rate first; b3 excluded.
    assert [r["bank"]["id"] for r in body["results"]] == [2, 1]
    for r in body["results"]:
        assert r["interest"] > 0
        assert r["final"] > r["interest"]


def test_simulate_invalid_amount_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(
        h,
        "BankRates",
        MagicMock(best_per_bank=MagicMock(side_effect=AssertionError("should not run"))),
    )

    resp = h.handler(_event({"amount": "-5", "term_days": 180}), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid_amount"}


def test_simulate_invalid_term_returns_400(load_handler):
    h = load_handler(__file__)

    resp = h.handler(_event({"amount": "1000000", "term_days": 45}), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid_term_days"}
