"""Unit tests for the processes/create Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock


def _authed_event(body: dict) -> dict:
    return {"headers": {"Authorization": "Bearer tok"}, "body": json.dumps(body)}


def _patch_auth(monkeypatch, user_id="u-1"):
    user = MagicMock(id=user_id)
    monkeypatch.setattr(
        "libs.utils.auth.verify_token",
        MagicMock(return_value=(user, MagicMock())),
    )
    return user


def test_processes_create_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)

    monkeypatch.setattr(
        h,
        "Banks",
        MagicMock(get_by_id=MagicMock(return_value=MagicMock(is_active=True))),
    )
    saved = MagicMock(public_dict=MagicMock(return_value={"id": "p-1", "stage": "form"}))
    monkeypatch.setattr(h, "Processes", MagicMock(create=MagicMock(return_value=saved)))

    resp = h.handler(
        _authed_event({"bank_id": 1, "amount": "1000000", "term_days": 180, "rate": "12.5"}), None
    )

    assert resp["statusCode"] == 201
    assert json.loads(resp["body"]) == {"process": {"id": "p-1", "stage": "form"}}


def test_processes_create_amount_out_of_range_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Banks", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))
    monkeypatch.setattr(h, "Processes", MagicMock(create=MagicMock(side_effect=AssertionError)))

    resp = h.handler(
        _authed_event({"bank_id": 1, "amount": "1", "term_days": 180, "rate": "10"}), None
    )

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "amount out of range"}


def test_processes_create_inactive_bank_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        h,
        "Banks",
        MagicMock(get_by_id=MagicMock(return_value=MagicMock(is_active=False))),
    )
    monkeypatch.setattr(h, "Processes", MagicMock(create=MagicMock(side_effect=AssertionError)))

    resp = h.handler(
        _authed_event({"bank_id": 999, "amount": "1000000", "term_days": 180, "rate": "10"}), None
    )

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "bank_not_found"}
