"""Unit tests for the processes/list_mine Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock


def _authed_event() -> dict:
    return {"headers": {"Authorization": "Bearer tok"}}


def _patch_auth(monkeypatch, user_id="u-1"):
    user = MagicMock(id=user_id)
    monkeypatch.setattr(
        "libs.utils.auth.verify_token",
        MagicMock(return_value=(user, MagicMock())),
    )
    return user


def test_list_mine_returns_user_processes(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    rows = [
        MagicMock(public_dict=MagicMock(return_value={"id": "p-1"})),
        MagicMock(public_dict=MagicMock(return_value={"id": "p-2"})),
    ]
    monkeypatch.setattr(h, "Processes", MagicMock(list_by_user=MagicMock(return_value=rows)))

    resp = h.handler(_authed_event(), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"processes": [{"id": "p-1"}, {"id": "p-2"}]}
    h.Processes.list_by_user.assert_called_once_with(user.id)


def test_list_mine_empty(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Processes", MagicMock(list_by_user=MagicMock(return_value=[])))

    resp = h.handler(_authed_event(), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"processes": []}


def test_list_mine_missing_bearer_returns_401(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Processes", MagicMock(list_by_user=MagicMock(side_effect=AssertionError)))

    resp = h.handler({"headers": {}}, None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "missing_bearer_token"}
