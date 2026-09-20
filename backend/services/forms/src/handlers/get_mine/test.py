"""Unit tests for the forms/get_mine Lambda."""
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


def test_get_mine_returns_form_when_present(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    form_row = MagicMock(public_dict=MagicMock(return_value={"full_name": "Foo"}))
    monkeypatch.setattr(h, "Forms", MagicMock(get_by_user=MagicMock(return_value=form_row)))

    resp = h.handler(_authed_event(), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"form": {"full_name": "Foo"}}
    h.Forms.get_by_user.assert_called_once_with(user.id)


def test_get_mine_returns_null_when_no_form(load_handler, monkeypatch):
    """A user without a filled form gets `null` instead of a 404 so the SPA
    can tell 'not filled yet' from 'error'."""
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Forms", MagicMock(get_by_user=MagicMock(return_value=None)))

    resp = h.handler(_authed_event(), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"form": None}


def test_get_mine_missing_bearer_returns_401(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Forms", MagicMock(get_by_user=MagicMock(side_effect=AssertionError)))

    resp = h.handler({"headers": {}}, None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "missing_bearer_token"}
