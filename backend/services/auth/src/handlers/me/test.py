"""Unit tests for the auth/me Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _authed_event(token: str = "tok") -> dict:
    return {"headers": {"Authorization": f"Bearer {token}"}}


# Happy path: valid bearer -> 200 with the authenticated user's public fields.
def test_me_happy_path(load_handler, monkeypatch):

    handler = load_handler(__file__)

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fake_user = MagicMock(
        id="u-1",
        email="a@b.co",
        full_name="Ana",
        created_at=now,
        updated_at=now,
    )
    fake_bearer = MagicMock(revoked_at=None)

    monkeypatch.setattr(
        "libs.utils.auth.BearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=fake_bearer)),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Users", MagicMock(get_by_id=MagicMock(return_value=fake_user)))

    resp = handler.handler(_authed_event(), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {
        "user": {
            "id": "u-1",
            "email": "a@b.co",
            "full_name": "Ana",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
    }


# No Authorization header -> 401 before require_auth touches the DB.
def test_me_missing_bearer_returns_401(load_handler):

    handler = load_handler(__file__)

    resp = handler.handler({"headers": {}}, None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "missing_bearer_token"}


# Bearer present but unknown to the DB -> 401.
def test_me_invalid_token_returns_401(load_handler, monkeypatch):

    handler = load_handler(__file__)

    monkeypatch.setattr(
        "libs.utils.auth.BearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=None)),
    )

    resp = handler.handler(_authed_event("bad-token"), None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "invalid_or_expired_token"}
