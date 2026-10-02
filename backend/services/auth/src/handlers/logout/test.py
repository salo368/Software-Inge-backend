"""Unit tests for the auth/logout Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock


def _authed_event(token: str = "tok") -> dict:
    return {"headers": {"Authorization": f"Bearer {token}"}}


# Happy path: valid bearer -> revoke() runs with the resolved token id and
# the handler answers 200.
def test_logout_happy_path(load_handler, monkeypatch):

    handler = load_handler(__file__)

    fake_user = MagicMock()
    fake_bearer = MagicMock(id="bearer-1", revoked_at=None)

    monkeypatch.setattr(
        "libs.utils.auth.BearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=fake_bearer)),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Users", MagicMock(get_by_id=MagicMock(return_value=fake_user)))
    monkeypatch.setattr(handler, "revoke", MagicMock())

    resp = handler.handler(_authed_event(), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"revoked": True}

    handler.revoke.assert_called_once_with("bearer-1")


# No Authorization header -> 401 before require_auth ever resolves a token,
# so revoke() must never run.
def test_logout_missing_bearer_returns_401(load_handler, monkeypatch):

    handler = load_handler(__file__)

    monkeypatch.setattr(handler, "revoke", MagicMock(side_effect=AssertionError))

    resp = handler.handler({"headers": {}}, None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "missing_bearer_token"}

    handler.revoke.assert_not_called()


# Bearer present but unknown to the DB -> 401, revoke() must never run.
def test_logout_invalid_token_returns_401(load_handler, monkeypatch):

    handler = load_handler(__file__)

    monkeypatch.setattr(
        "libs.utils.auth.BearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=None)),
    )
    monkeypatch.setattr(handler, "revoke", MagicMock(side_effect=AssertionError))

    resp = handler.handler(_authed_event("bad"), None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "invalid_or_expired_token"}

    handler.revoke.assert_not_called()
