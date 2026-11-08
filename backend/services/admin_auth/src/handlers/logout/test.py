"""Unit tests for the admin_auth/logout Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock


def _authed_event(token: str = "tok") -> dict:
    return {"headers": {"Authorization": f"Bearer {token}"}}


def test_logout_revokes_the_admin_token(load_handler, monkeypatch):
    handler = load_handler(__file__)
    monkeypatch.setattr(
        "libs.utils.auth.AdminBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(id="bearer-1", revoked_at=None, admin_id="a-1"))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Admins", MagicMock(get_by_id=MagicMock(return_value=MagicMock())))
    monkeypatch.setattr(handler, "revoke", MagicMock())

    resp = handler.handler(_authed_event(), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"revoked": True}
    handler.revoke.assert_called_once_with("bearer-1", handler.AuthsTypes.INTERNAL)


def test_logout_missing_bearer_returns_401_and_never_revokes(load_handler, monkeypatch):
    handler = load_handler(__file__)
    monkeypatch.setattr(handler, "revoke", MagicMock(side_effect=AssertionError))

    resp = handler.handler({"headers": {}}, None)

    assert resp["statusCode"] == 401
    handler.revoke.assert_not_called()


def test_logout_user_token_is_rejected_and_never_revokes(load_handler, monkeypatch):
    handler = load_handler(__file__)
    monkeypatch.setattr("libs.utils.auth.AdminBearerTokens", MagicMock(get_by_hash=MagicMock(return_value=None)))
    monkeypatch.setattr(handler, "revoke", MagicMock(side_effect=AssertionError))

    resp = handler.handler(_authed_event("a-user-token"), None)

    assert resp["statusCode"] == 401
    handler.revoke.assert_not_called()
