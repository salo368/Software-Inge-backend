"""Unit tests for the admin_auth/register Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _event(body: dict | None, headers: dict | None = None) -> dict:
    return {
        "headers": headers if headers is not None else {"Authorization": "Bearer tok"},
        "body": json.dumps(body) if body is not None else None,
    }


def _patch_admin_auth(monkeypatch):
    monkeypatch.setattr(
        "libs.utils.auth.AdminBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None, admin_id="a-1"))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Admins", MagicMock(get_by_id=MagicMock(return_value=MagicMock(id="a-1"))))


def _patch(handler, monkeypatch, *, existing=None):
    now = datetime.now(timezone.utc)
    created = MagicMock(id="a-2", email="new@co.co", full_name="New Admin", created_at=now, updated_at=now)
    admins = MagicMock(get_by_email=MagicMock(return_value=existing), create=MagicMock(return_value=created))
    credentials = MagicMock(create=MagicMock())
    monkeypatch.setattr(handler, "Admins", admins)
    monkeypatch.setattr(handler, "AdminCredentials", credentials)
    monkeypatch.setattr(handler, "hash_password", MagicMock(return_value="hashed-pw"))
    return admins, credentials, now


def test_register_by_an_admin_creates_the_new_admin(load_handler, monkeypatch):
    handler = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    admins, credentials, now = _patch(handler, monkeypatch)

    resp = handler.handler(_event({"email": "NEW@co.co", "password": "hunter22aa", "full_name": " New Admin "}), None)

    assert resp["statusCode"] == 201
    assert json.loads(resp["body"]) == {
        "admin": {
            "id": "a-2",
            "email": "new@co.co",
            "full_name": "New Admin",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
    }
    admins.create.assert_called_once_with(email="new@co.co", full_name="New Admin")
    credentials.create.assert_called_once_with(admin_id="a-2", password_hash="hashed-pw")


def test_register_does_not_issue_a_token(load_handler, monkeypatch):
    handler = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    _patch(handler, monkeypatch)

    resp = handler.handler(_event({"email": "new@co.co", "password": "hunter22aa", "full_name": "New"}), None)

    assert "token" not in json.loads(resp["body"])


def test_register_requires_an_admin_token(load_handler, monkeypatch):
    handler = load_handler(__file__)
    admins, credentials, _ = _patch(handler, monkeypatch)

    resp = handler.handler(_event({"email": "new@co.co", "password": "hunter22aa", "full_name": "New"}, headers={}), None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "missing_bearer_token"}
    admins.create.assert_not_called()
    credentials.create.assert_not_called()


def test_register_rejects_a_user_token(load_handler, monkeypatch):
    handler = load_handler(__file__)
    monkeypatch.setattr("libs.utils.auth.AdminBearerTokens", MagicMock(get_by_hash=MagicMock(return_value=None)))
    admins, credentials, _ = _patch(handler, monkeypatch)

    resp = handler.handler(_event({"email": "new@co.co", "password": "hunter22aa", "full_name": "New"}), None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "invalid_or_expired_token"}
    admins.create.assert_not_called()
    credentials.create.assert_not_called()


def test_register_validations(load_handler, monkeypatch):
    handler = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    admins, credentials, _ = _patch(handler, monkeypatch)

    cases = [
        ({}, "missing_fields"),
        ({"email": "new@co.co", "password": "hunter22aa"}, "missing_fields"),
        ({"email": "not-an-email", "password": "hunter22aa", "full_name": "New"}, "invalid_email"),
        ({"email": "new@co.co", "password": "short1", "full_name": "New"}, "password_too_short"),
        ({"email": "new@co.co", "password": "1234567890", "full_name": "New"}, "password_needs_letter"),
        ({"email": "new@co.co", "password": "abcdefghij", "full_name": "New"}, "password_needs_digit"),
    ]
    for body, error in cases:
        resp = handler.handler(_event(body), None)

        assert resp["statusCode"] == 400, body
        assert json.loads(resp["body"]) == {"error": error}
    admins.create.assert_not_called()
    credentials.create.assert_not_called()


def test_register_duplicate_email_returns_409(load_handler, monkeypatch):
    handler = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    admins, credentials, _ = _patch(handler, monkeypatch, existing=MagicMock())

    resp = handler.handler(_event({"email": "new@co.co", "password": "hunter22aa", "full_name": "New"}), None)

    assert resp["statusCode"] == 409
    assert json.loads(resp["body"]) == {"error": "email_taken"}
    admins.create.assert_not_called()
    credentials.create.assert_not_called()
