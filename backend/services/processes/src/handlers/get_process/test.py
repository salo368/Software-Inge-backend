"""Unit tests for the processes/get_process Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID

_PID = "7077c70e-d8bf-4c8e-97ef-a7e0909949df"


def _event(**kwargs):
    return {"headers": {"Authorization": "Bearer tok"}, **kwargs}


def _patch_user_auth(monkeypatch, user_id="u-1"):
    user = MagicMock(id=user_id)
    monkeypatch.setattr(
        "libs.utils.auth.UserBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Users", MagicMock(get_by_id=MagicMock(return_value=user)))
    return user


def _patch_admin_auth(monkeypatch):
    monkeypatch.setattr("libs.utils.auth.UserBearerTokens", MagicMock(get_by_hash=MagicMock(return_value=None)))
    monkeypatch.setattr(
        "libs.utils.auth.AdminBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None, admin_id="a-1"))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Admins", MagicMock(get_by_id=MagicMock(return_value=MagicMock(id="a-1"))))


def _process(user_id="u-1"):
    return MagicMock(
        id=UUID(_PID), user_id=user_id, bank_id=1, amount=Decimal("1000000.00"), term=180,
        rate=Decimal("12.50"), stage="PAYMENT", signature_id=None, submitted_form={"name": "Ana"},
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )


def _patch_processes(h, monkeypatch, process):
    processes = MagicMock(get_by_id=MagicMock(return_value=process))
    monkeypatch.setattr(h, "Processes", processes)
    return processes


def test_get_process_user_gets_own_process(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_user_auth(monkeypatch)
    processes = _patch_processes(h, monkeypatch, _process(user_id="u-1"))

    resp = h.handler(_event(queryStringParameters={"process_id": _PID}), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["process"] == {
        "id": _PID, "user_id": "u-1", "bank_id": 1, "amount": 1000000.0, "term": 180, "rate": 12.5,
        "stage": "PAYMENT", "signature_id": None, "submitted_form": {"name": "Ana"},
        "created_at": "2026-01-01 00:00:00+00:00", "updated_at": "2026-01-02 00:00:00+00:00",
    }
    processes.get_by_id.assert_called_once_with(UUID(_PID))


def test_get_process_user_cannot_see_someone_elses(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_user_auth(monkeypatch, user_id="u-1")
    _patch_processes(h, monkeypatch, _process(user_id="u-2"))

    resp = h.handler(_event(queryStringParameters={"process_id": _PID}), None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "process_not_found"}


def test_get_process_admin_sees_any_process_without_user_id(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    _patch_processes(h, monkeypatch, _process(user_id="u-77"))

    resp = h.handler(_event(body=json.dumps({"process_id": _PID})), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["process"]["user_id"] == "u-77"


def test_get_process_not_found(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    _patch_processes(h, monkeypatch, None)

    resp = h.handler(_event(queryStringParameters={"process_id": _PID}), None)

    assert resp["statusCode"] == 404


def test_get_process_invalid_process_id(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_user_auth(monkeypatch)
    processes = _patch_processes(h, monkeypatch, None)

    for event in (_event(), _event(queryStringParameters={"process_id": "nope"})):
        resp = h.handler(event, None)

        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "invalid process id"}
    processes.get_by_id.assert_not_called()


def test_get_process_requires_auth(load_handler):
    h = load_handler(__file__)

    resp = h.handler({"headers": {}}, None)

    assert resp["statusCode"] == 401
