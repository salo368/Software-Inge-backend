"""Unit tests for the processes/create_process Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from libs.utils.lambda_invoke import LambdaInvokeError


def _authed_event(body: dict) -> dict:
    return {"headers": {"Authorization": "Bearer tok"}, "body": json.dumps(body)}


def _patch_auth(monkeypatch, user_id="u-1"):
    user = MagicMock(id=user_id)
    monkeypatch.setattr(
        "libs.utils.auth.UserBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Users", MagicMock(get_by_id=MagicMock(return_value=user)))
    return user


def _simulate_response(banks: dict, status_code=200):
    return {"statusCode": status_code, "body": json.dumps({"banks": banks})}


def _fake_process(**overrides):
    defaults = dict(
        id="p-1",
        bank_id=1,
        amount=Decimal("1000000.00"),
        term=180,
        rate=Decimal("12.50"),
        stage="FORM",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def test_create_process_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    monkeypatch.setattr(
        h,
        "invoke_sync",
        MagicMock(return_value=_simulate_response({"1": {"rate": 12.5}})),
    )
    created = _fake_process()
    create_mock = MagicMock(return_value=created)
    monkeypatch.setattr(h, "Processes", MagicMock(create=create_mock))

    resp = h.handler(_authed_event({"bank_id": 1, "amount": "1000000", "term": 180}), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {
        "id": "p-1",
        "bank_id": 1,
        "amount": 1000000.0,
        "term": 180,
        "rate": 12.5,
        "stage": "FORM",
        "created_at": "2026-01-01 00:00:00+00:00",
    }

    create_mock.assert_called_once_with(
        user_id=user.id,
        bank_id=1,
        amount=Decimal("1000000"),
        term=180,
        rate=Decimal("12.5"),
    )


def test_create_process_missing_fields_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)

    resp = h.handler(_authed_event({"bank_id": 1, "amount": "1000000"}), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "Missing required fields"}


def test_create_process_simulation_unavailable_returns_502(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        h,
        "invoke_sync",
        MagicMock(side_effect=LambdaInvokeError("cdts-test-banks-simulate", "boto_error", "timeout")),
    )

    resp = h.handler(_authed_event({"bank_id": 1, "amount": "1000000", "term": 180}), None)

    assert resp["statusCode"] == 502
    assert json.loads(resp["body"]) == {"error": "simulation_unavailable"}


def test_create_process_propagates_simulation_error(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        h,
        "invoke_sync",
        MagicMock(return_value={"statusCode": 400, "body": json.dumps({"error": "invalid_amount"})}),
    )

    resp = h.handler(_authed_event({"bank_id": 1, "amount": "1", "term": 180}), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid_amount"}


def test_create_process_bank_not_available_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        h,
        "invoke_sync",
        MagicMock(return_value=_simulate_response({"2": {"rate": 12.5}})),
    )

    resp = h.handler(_authed_event({"bank_id": 1, "amount": "1000000", "term": 180}), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "Bank not available for the given amount and term"}
