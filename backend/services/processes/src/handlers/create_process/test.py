"""Unit tests for the processes/create_process Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from libs.utils.lambda_invoke import LambdaInvokeError


def _authed_event(body: dict) -> dict:
    return {"headers": {"Authorization": "Bearer tok"}, "body": json.dumps(body)}


def _patch_auth(monkeypatch, user_id="u-1"):
    user = MagicMock(id=user_id)
    monkeypatch.setattr(
        "libs.utils.auth.BearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Users", MagicMock(get_by_id=MagicMock(return_value=user)))
    return user


def _simulate_response(banks: dict, status_code=200):
    return {"statusCode": status_code, "body": json.dumps({"banks": banks})}


def test_create_process_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)

    monkeypatch.setattr(
        h,
        "invoke_sync",
        MagicMock(return_value=_simulate_response({"1": {"rate": 12.5}})),
    )

    resp = h.handler(_authed_event({"bank_id": 1, "amount": "1000000", "term": 180}), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"amount": 1000000.0, "term": 180, "valid": True}


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


def test_create_process_invalid_amount_or_term_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "invoke_sync", MagicMock(return_value=_simulate_response({}, status_code=400)))

    resp = h.handler(_authed_event({"bank_id": 1, "amount": "1", "term": 180}), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid_amount_or_term"}


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
