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


def test_login_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)

    fake_user = MagicMock(
        id="u-1",
        password_hash="stored-hash",
        public_dict=MagicMock(return_value={"id": "u-1", "email": "a@b.co"}),
    )
    monkeypatch.setattr(h, "Users", MagicMock(get_by_email=MagicMock(return_value=fake_user)))
    monkeypatch.setattr(h, "verify_password", MagicMock(return_value=True))
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    monkeypatch.setattr(h, "issue_token", MagicMock(return_value=("plain-token", expires)))

    resp = h.handler(_event({"email": "A@B.co", "password": "hunter22"}), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["token"] == "plain-token"
    assert body["expires_at"] == expires.isoformat()
    assert body["user"] == {"id": "u-1", "email": "a@b.co"}
    # email must have been lowercased/stripped before hitting the ORM
    h.Users.get_by_email.assert_called_once_with("a@b.co")


def test_login_missing_fields_returns_400(load_handler):
    h = load_handler(__file__)

    resp = h.handler(_event({"email": "", "password": ""}), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "missing_fields"}


def test_login_wrong_password_returns_401(load_handler, monkeypatch):
    h = load_handler(__file__)

    fake_user = MagicMock(password_hash="stored-hash")
    monkeypatch.setattr(h, "Users", MagicMock(get_by_email=MagicMock(return_value=fake_user)))
    monkeypatch.setattr(h, "verify_password", MagicMock(return_value=False))
    # If issue_token got called we would know the guard is broken.
    monkeypatch.setattr(h, "issue_token", MagicMock(side_effect=AssertionError("should not run")))

    resp = h.handler(_event({"email": "a@b.co", "password": "wrong"}), None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "invalid_credentials"}
