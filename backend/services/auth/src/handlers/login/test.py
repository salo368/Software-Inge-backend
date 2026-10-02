"""Unit tests for the auth/login Lambda.

Covers the three-case minimum required by the repo convention (see
docs/repo-structure.md §8):
  * happy path
  * request validation
  * domain-level rejection (bad credentials)

External calls (Users ORM, password verify, token issuance) are monkeypatched
so no real DB or AWS call happens.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


def _event(body: dict | None) -> dict:
    return {"body": json.dumps(body) if body is not None else None}


# Happy path: known email, matching password -> 200 with the user, a fresh
# token, and its expiry.
def test_login_happy_path(load_handler, monkeypatch):

    handler = load_handler(__file__)

    now = datetime.now(timezone.utc)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)

    fake_user = MagicMock(
        id="u-1",
        email="a@b.co",
        full_name="Ana",
        created_at=now,
        updated_at=now,
    )
    fake_credentials = MagicMock(password_hash="stored-hash")

    monkeypatch.setattr(handler, "Users", MagicMock(get_by_email=MagicMock(return_value=fake_user)))
    monkeypatch.setattr(
        handler,
        "UserCredentials",
        MagicMock(get_by_user_id=MagicMock(return_value=fake_credentials)),
    )
    monkeypatch.setattr(handler, "verify_password", MagicMock(return_value=True))
    monkeypatch.setattr(handler, "issue_token", MagicMock(return_value=("plain-token", expires)))

    resp = handler.handler(
        _event(
            {
                "email": "A@B.co",
                "password": "hunter22",
            }
        ),
        None,
    )

    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    assert body["token"] == "plain-token"
    assert body["expires_at"] == expires.isoformat()
    assert body["user"] == {
        "id": "u-1",
        "email": "a@b.co",
        "full_name": "Ana",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    # email must have been lowercased/stripped before hitting the ORM
    handler.Users.get_by_email.assert_called_once_with("a@b.co")


# Empty email/password -> 400 before any ORM call.
def test_login_missing_fields_returns_400(load_handler):

    handler = load_handler(__file__)

    resp = handler.handler(
        _event(
            {
                "email": "",
                "password": "",
            }
        ),
        None,
    )

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "missing_fields"}


# Known email, wrong password -> 401, and issue_token must never run.
def test_login_wrong_password_returns_401(load_handler, monkeypatch):

    handler = load_handler(__file__)

    fake_user = MagicMock(id="u-1")
    fake_credentials = MagicMock(password_hash="stored-hash")

    monkeypatch.setattr(handler, "Users", MagicMock(get_by_email=MagicMock(return_value=fake_user)))
    monkeypatch.setattr(
        handler,
        "UserCredentials",
        MagicMock(get_by_user_id=MagicMock(return_value=fake_credentials)),
    )
    monkeypatch.setattr(handler, "verify_password", MagicMock(return_value=False))
    # If issue_token got called we would know the guard is broken.
    monkeypatch.setattr(handler, "issue_token", MagicMock(side_effect=AssertionError("should not run")))

    resp = handler.handler(
        _event(
            {
                "email": "a@b.co",
                "password": "wrong",
            }
        ),
        None,
    )

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "invalid_credentials"}
