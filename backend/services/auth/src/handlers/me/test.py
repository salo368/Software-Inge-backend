"""Unit tests for the auth/me Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock


def _authed_event(token: str = "tok") -> dict:
    return {"headers": {"Authorization": f"Bearer {token}"}}


def test_me_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)

    fake_user = MagicMock(public_dict=MagicMock(return_value={"id": "u-1", "email": "a@b.co"}))
    fake_bearer = MagicMock()
    monkeypatch.setattr("libs.utils.auth.verify_token", MagicMock(return_value=(fake_user, fake_bearer)))

    resp = h.handler(_authed_event(), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"user": {"id": "u-1", "email": "a@b.co"}}


def test_me_missing_bearer_returns_401(load_handler):
    h = load_handler(__file__)

    resp = h.handler({"headers": {}}, None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "missing_bearer_token"}


def test_me_invalid_token_returns_401(load_handler, monkeypatch):
    h = load_handler(__file__)

    from libs.core.responses import HandledError
    monkeypatch.setattr(
        "libs.utils.auth.verify_token",
        MagicMock(side_effect=HandledError("invalid_or_expired_token", 401)),
    )

    resp = h.handler(_authed_event("bad-token"), None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "invalid_or_expired_token"}
