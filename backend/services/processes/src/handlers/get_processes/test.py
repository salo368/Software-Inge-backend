"""Unit tests for the processes/get_processes Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock


def _authed_event() -> dict:
    return {"headers": {"Authorization": "Bearer tok"}}


def _patch_auth(monkeypatch, user_id="u-1"):
    user = MagicMock(id=user_id)
    monkeypatch.setattr(
        "libs.utils.auth.UserBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Users", MagicMock(get_by_id=MagicMock(return_value=user)))
    return user


def _fake_process(**overrides):
    defaults = dict(
        id="p-1",
        bank_id=1,
        amount=Decimal("1000000.00"),
        term=180,
        rate=Decimal("12.50"),
        stage="FORM",
        signature_id=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def test_get_processes_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    rows = [
        _fake_process(id="p-1"),
        _fake_process(
            id="p-2", bank_id=2, stage="SIGNATURE",
            signature_id="7077c70e-d8bf-4c8e-97ef-a7e0909949df",
        ),
    ]
    list_mock = MagicMock(return_value=rows)
    monkeypatch.setattr(h, "Processes", MagicMock(list_by_user=list_mock))

    resp = h.handler(_authed_event(), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {
        "processes": [
            {
                "id": "p-1",
                "bank_id": 1,
                "amount": 1000000.0,
                "term": 180,
                "rate": 12.5,
                "stage": "FORM",
                "signature_id": None,
                "created_at": "2026-01-01 00:00:00+00:00",
            },
            {
                "id": "p-2",
                "bank_id": 2,
                "amount": 1000000.0,
                "term": 180,
                "rate": 12.5,
                "stage": "SIGNATURE",
                "signature_id": "7077c70e-d8bf-4c8e-97ef-a7e0909949df",
                "created_at": "2026-01-01 00:00:00+00:00",
            },
        ]
    }
    list_mock.assert_called_once_with(user.id)


def test_get_processes_empty(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Processes", MagicMock(list_by_user=MagicMock(return_value=[])))

    resp = h.handler(_authed_event(), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"processes": []}


def test_get_processes_requires_auth(load_handler):
    h = load_handler(__file__)

    resp = h.handler({"headers": {}}, None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "missing_bearer_token"}
