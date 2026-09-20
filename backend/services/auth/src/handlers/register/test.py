"""Unit tests for the auth/register Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


def _event(body: dict | None) -> dict:
    return {"body": json.dumps(body) if body is not None else None}


def test_register_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)

    created_user = MagicMock(
        id="u-1",
        public_dict=MagicMock(return_value={"id": "u-1", "email": "new@user.co"}),
    )
    monkeypatch.setattr(
        h,
        "Users",
        MagicMock(
            get_by_email=MagicMock(return_value=None),
            create=MagicMock(return_value=created_user),
        ),
    )
    monkeypatch.setattr(h, "hash_password", MagicMock(return_value="hashed-pw"))
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    monkeypatch.setattr(h, "issue_token", MagicMock(return_value=("plain-token", expires)))

    resp = h.handler(
        _event({"email": "new@user.co", "password": "hunter22aa", "full_name": "Nueva Usuaria"}),
        None,
    )

    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["user"] == {"id": "u-1", "email": "new@user.co"}
    assert body["token"] == "plain-token"
    h.Users.create.assert_called_once_with(
        email="new@user.co", password_hash="hashed-pw", full_name="Nueva Usuaria"
    )


def test_register_invalid_email_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    # Users.get_by_email would only be called after validation; monkeypatch to
    # blow up so we know the guard catches the bad input first.
    monkeypatch.setattr(h, "Users", MagicMock(get_by_email=MagicMock(side_effect=AssertionError)))

    resp = h.handler(
        _event({"email": "not-an-email", "password": "hunter22aa", "full_name": "Foo"}),
        None,
    )

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid_email"}


def test_register_email_taken_returns_409(load_handler, monkeypatch):
    h = load_handler(__file__)

    monkeypatch.setattr(
        h, "Users", MagicMock(get_by_email=MagicMock(return_value=MagicMock()), create=MagicMock())
    )
    monkeypatch.setattr(h, "hash_password", MagicMock(return_value="x"))

    resp = h.handler(
        _event({"email": "taken@x.co", "password": "hunter22aa", "full_name": "Foo Bar"}),
        None,
    )

    assert resp["statusCode"] == 409
    assert json.loads(resp["body"]) == {"error": "email_taken"}
    h.Users.create.assert_not_called()
