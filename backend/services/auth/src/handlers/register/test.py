"""Unit tests for the auth/register Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


def _event(body: dict | None) -> dict:
    return {"body": json.dumps(body) if body is not None else None}


# Happy path: new email, valid password, full_name present -> creates the
# user, creates their credentials, issues a token, and responds 201 with the user.
def test_register_happy_path(load_handler, monkeypatch):

    handler = load_handler(__file__)

    now = datetime.now(timezone.utc)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)

    created_user = MagicMock(
        id="u-1",
        email="new@user.co",
        full_name="New User",
        created_at=now,
        updated_at=now,
    )

    monkeypatch.setattr(
        handler,
        "Users",
        MagicMock(
            get_by_email=MagicMock(return_value=None),
            create=MagicMock(return_value=created_user),
        ),
    )
    monkeypatch.setattr(handler, "UserCredentials", MagicMock(create=MagicMock()))
    monkeypatch.setattr(handler, "hash_password", MagicMock(return_value="hashed-pw"))
    monkeypatch.setattr(handler, "issue_token", MagicMock(return_value=("plain-token", expires)))

    resp = handler.handler(
        _event(
            {
                "email": "new@user.co",
                "password": "hunter22aa",
                "full_name": "New User",
            }
        ),
        None,
    )

    assert resp["statusCode"] == 201

    body = json.loads(resp["body"])
    assert body["user"] == {
        "id": "u-1",
        "email": "new@user.co",
        "full_name": "New User",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    assert body["token"] == "plain-token"

    handler.Users.create.assert_called_once_with(email="new@user.co", full_name="New User")
    handler.UserCredentials.create.assert_called_once_with(user_id="u-1", password_hash="hashed-pw")


# Malformed email -> rejected by validation before ever touching the ORM.
def test_register_invalid_email_returns_400(load_handler, monkeypatch):

    handler = load_handler(__file__)

    monkeypatch.setattr(
        handler,
        "Users",
        MagicMock(get_by_email=MagicMock(side_effect=AssertionError)),
    )

    resp = handler.handler(
        _event(
            {
                "email": "not-an-email",
                "password": "hunter22aa",
                "full_name": "Foo",
            }
        ),
        None,
    )

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid_email"}


# Email already registered -> 409 and Users.create must never be called.
def test_register_email_taken_returns_409(load_handler, monkeypatch):

    handler = load_handler(__file__)

    monkeypatch.setattr(
        handler,
        "Users",
        MagicMock(
            get_by_email=MagicMock(return_value=MagicMock()),
            create=MagicMock(),
        ),
    )
    monkeypatch.setattr(handler, "hash_password", MagicMock(return_value="x"))

    resp = handler.handler(
        _event(
            {
                "email": "taken@x.co",
                "password": "hunter22aa",
                "full_name": "Foo Bar",
            }
        ),
        None,
    )

    assert resp["statusCode"] == 409
    assert json.loads(resp["body"]) == {"error": "email_taken"}

    handler.Users.create.assert_not_called()
