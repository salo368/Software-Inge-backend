"""Unit tests for the admin_auth/login Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


def _event(body: dict | None) -> dict:
    return {"body": json.dumps(body) if body is not None else None}


def _patch(handler, monkeypatch, *, admin, credentials=None, valid=True):
    monkeypatch.setattr(handler, "Admins", MagicMock(get_by_email=MagicMock(return_value=admin)))
    monkeypatch.setattr(handler, "AdminCredentials", MagicMock(get_by_admin_id=MagicMock(return_value=credentials)))
    monkeypatch.setattr(handler, "verify_password", MagicMock(return_value=valid))
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    monkeypatch.setattr(handler, "issue_token", MagicMock(return_value=("plain-token", expires)))
    return expires


def test_login_happy_path_issues_an_internal_token(load_handler, monkeypatch):
    handler = load_handler(__file__)
    now = datetime.now(timezone.utc)
    admin = MagicMock(id="a-1", email="root@co.co", full_name="Root", created_at=now, updated_at=now)
    expires = _patch(handler, monkeypatch, admin=admin, credentials=MagicMock(password_hash="stored"))

    resp = handler.handler(_event({"email": "ROOT@co.co", "password": "hunter22aa"}), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {
        "admin": {
            "id": "a-1",
            "email": "root@co.co",
            "full_name": "Root",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        },
        "token": "plain-token",
        "expires_at": expires.isoformat(),
    }
    handler.Admins.get_by_email.assert_called_once_with("root@co.co")
    handler.issue_token.assert_called_once_with("a-1", handler.AuthsTypes.INTERNAL)


def test_login_missing_fields_returns_400(load_handler, monkeypatch):
    handler = load_handler(__file__)
    _patch(handler, monkeypatch, admin=None)

    for body in ({}, {"email": "a@b.co"}, {"password": "x"}, None):
        resp = handler.handler(_event(body), None)

        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "missing_fields"}


def test_login_unknown_email_returns_401_without_issuing_a_token(load_handler, monkeypatch):
    handler = load_handler(__file__)
    _patch(handler, monkeypatch, admin=None)

    resp = handler.handler(_event({"email": "no@one.co", "password": "hunter22aa"}), None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "invalid_credentials"}
    handler.issue_token.assert_not_called()


def test_login_wrong_password_returns_401_without_issuing_a_token(load_handler, monkeypatch):
    handler = load_handler(__file__)
    _patch(handler, monkeypatch, admin=MagicMock(id="a-1"), credentials=MagicMock(password_hash="stored"), valid=False)

    resp = handler.handler(_event({"email": "root@co.co", "password": "wrong"}), None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "invalid_credentials"}
    handler.issue_token.assert_not_called()


def test_login_admin_without_credentials_returns_401(load_handler, monkeypatch):
    handler = load_handler(__file__)
    _patch(handler, monkeypatch, admin=MagicMock(id="a-1"), credentials=None)

    resp = handler.handler(_event({"email": "root@co.co", "password": "hunter22aa"}), None)

    assert resp["statusCode"] == 401
    handler.issue_token.assert_not_called()
