"""Unit tests for the auth/logout Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock


def _authed_event(token: str = "tok") -> dict:
    return {"headers": {"Authorization": f"Bearer {token}"}}


def test_logout_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)

    fake_user = MagicMock()
    fake_bearer = MagicMock(id="bearer-1")
    monkeypatch.setattr("libs.utils.auth.verify_token", MagicMock(return_value=(fake_user, fake_bearer)))
    monkeypatch.setattr(h, "BearerTokens", MagicMock(revoke=MagicMock()))

    resp = h.handler(_authed_event(), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"revoked": True}
    h.BearerTokens.revoke.assert_called_once_with("bearer-1")


def test_logout_missing_bearer_returns_401(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "BearerTokens", MagicMock(revoke=MagicMock(side_effect=AssertionError)))

    resp = h.handler({"headers": {}}, None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "missing_bearer_token"}
    h.BearerTokens.revoke.assert_not_called()


def test_logout_invalid_token_returns_401(load_handler, monkeypatch):
    h = load_handler(__file__)

    from libs.core.responses import HandledError
    monkeypatch.setattr(
        "libs.utils.auth.verify_token",
        MagicMock(side_effect=HandledError("invalid_or_expired_token", 401)),
    )
    monkeypatch.setattr(h, "BearerTokens", MagicMock(revoke=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_authed_event("bad"), None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "invalid_or_expired_token"}
    h.BearerTokens.revoke.assert_not_called()
