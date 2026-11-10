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


def _patch_admin_auth(monkeypatch):
    # Not a user token: the user table finds nothing, the admin table does.
    monkeypatch.setattr("libs.utils.auth.UserBearerTokens", MagicMock(get_by_hash=MagicMock(return_value=None)))
    monkeypatch.setattr(
        "libs.utils.auth.AdminBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None, admin_id="a-1"))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Admins", MagicMock(get_by_id=MagicMock(return_value=MagicMock(id="a-1"))))


_TARGET = "7077c70e-d8bf-4c8e-97ef-a7e0909949df"


def test_get_processes_admin_lists_the_given_user(load_handler, monkeypatch):
    from uuid import UUID

    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    list_mock = MagicMock(return_value=[_fake_process(id="p-9")])
    monkeypatch.setattr(h, "Processes", MagicMock(list_by_user=list_mock))

    for event in (
        {"headers": {"Authorization": "Bearer adm"}, "queryStringParameters": {"user_id": _TARGET}},
        {"headers": {"Authorization": "Bearer adm"}, "body": json.dumps({"user_id": _TARGET})},
    ):
        resp = h.handler(event, None)

        assert resp["statusCode"] == 200
        assert [p["id"] for p in json.loads(resp["body"])["processes"]] == ["p-9"]
    list_mock.assert_called_with(UUID(_TARGET))


def test_get_processes_admin_without_user_id_is_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    processes = MagicMock()
    monkeypatch.setattr(h, "Processes", processes)

    resp = h.handler(_authed_event(), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid user id"}
    processes.list_by_user.assert_not_called()


def test_get_processes_user_cannot_pick_another_user(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)
    list_mock = MagicMock(return_value=[])
    monkeypatch.setattr(h, "Processes", MagicMock(list_by_user=list_mock))

    event = {"headers": {"Authorization": "Bearer tok"}, "queryStringParameters": {"user_id": _TARGET}}
    h.handler(event, None)

    list_mock.assert_called_once_with(user.id)
