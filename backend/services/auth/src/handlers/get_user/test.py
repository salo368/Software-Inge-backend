"""Unit tests for the auth/get_user Lambda (backoffice, admin only)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import UUID

_UID = "7077c70e-d8bf-4c8e-97ef-a7e0909949df"
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _patch_admin_auth(monkeypatch):
    monkeypatch.setattr(
        "libs.utils.auth.AdminBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None, admin_id="a-1"))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Admins", MagicMock(get_by_id=MagicMock(return_value=MagicMock(id="a-1"))))


def _event(**kwargs):
    return {"headers": {"Authorization": "Bearer adm"}, **kwargs}


def test_get_user_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    user = MagicMock(id=UUID(_UID), email="a@b.co", full_name="Ana", created_at=_NOW, updated_at=_NOW)
    users = MagicMock(get_by_id=MagicMock(return_value=user))
    monkeypatch.setattr(h, "Users", users)

    resp = h.handler(_event(queryStringParameters={"user_id": _UID}), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"user": {
        "id": _UID, "email": "a@b.co", "full_name": "Ana",
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
    }}
    users.get_by_id.assert_called_once_with(UUID(_UID))


def test_get_user_reads_body_too(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    users = MagicMock(get_by_id=MagicMock(return_value=None))
    monkeypatch.setattr(h, "Users", users)

    resp = h.handler(_event(body=json.dumps({"user_id": _UID})), None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "user_not_found"}


def test_get_user_invalid_user_id(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    users = MagicMock()
    monkeypatch.setattr(h, "Users", users)

    for event in (_event(), _event(queryStringParameters={"user_id": "nope"})):
        resp = h.handler(event, None)

        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "invalid user id"}
    users.get_by_id.assert_not_called()


def test_get_user_user_token_is_rejected(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr("libs.utils.auth.AdminBearerTokens", MagicMock(get_by_hash=MagicMock(return_value=None)))
    users = MagicMock()
    monkeypatch.setattr(h, "Users", users)

    resp = h.handler(_event(queryStringParameters={"user_id": _UID}), None)

    assert resp["statusCode"] == 401
    users.get_by_id.assert_not_called()
