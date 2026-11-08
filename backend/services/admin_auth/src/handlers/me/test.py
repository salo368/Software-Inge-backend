"""Unit tests for the admin_auth/me Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _authed_event(token: str = "tok") -> dict:
    return {"headers": {"Authorization": f"Bearer {token}"}}


def _patch_admin_auth(monkeypatch, admin):
    monkeypatch.setattr(
        "libs.utils.auth.AdminBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None, admin_id=admin.id))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Admins", MagicMock(get_by_id=MagicMock(return_value=admin)))


def test_me_returns_the_authenticated_admin(load_handler, monkeypatch):
    handler = load_handler(__file__)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    admin = MagicMock(id="a-1", email="root@co.co", full_name="Root", created_at=now, updated_at=now)
    _patch_admin_auth(monkeypatch, admin)

    resp = handler.handler(_authed_event(), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {
        "admin": {
            "id": "a-1",
            "email": "root@co.co",
            "full_name": "Root",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
    }


def test_me_missing_bearer_returns_401(load_handler):
    handler = load_handler(__file__)

    resp = handler.handler({"headers": {}}, None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "missing_bearer_token"}


def test_me_user_token_is_rejected(load_handler, monkeypatch):
    """A user token only exists in user_bearer_tokens: the admin lookup misses."""
    handler = load_handler(__file__)
    monkeypatch.setattr("libs.utils.auth.AdminBearerTokens", MagicMock(get_by_hash=MagicMock(return_value=None)))
    user_tokens = MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None, user_id="u-1")))
    monkeypatch.setattr("libs.utils.auth.UserBearerTokens", user_tokens)

    resp = handler.handler(_authed_event("a-user-token"), None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "invalid_or_expired_token"}
    user_tokens.get_by_hash.assert_not_called()
