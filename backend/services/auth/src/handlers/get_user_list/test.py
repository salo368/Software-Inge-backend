"""Unit tests for the auth/get_user_list Lambda (backoffice, admin only)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _patch_admin_auth(monkeypatch):
    monkeypatch.setattr(
        "libs.utils.auth.AdminBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None, admin_id="a-1"))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Admins", MagicMock(get_by_id=MagicMock(return_value=MagicMock(id="a-1"))))


def _event(body=None, query=None):
    event = {"headers": {"Authorization": "Bearer adm"}}
    if body is not None:
        event["body"] = json.dumps(body)
    if query is not None:
        event["queryStringParameters"] = query
    return event


def _user(n):
    return MagicMock(id=f"u-{n}", email=f"u{n}@x.co", full_name=f"User {n}", created_at=_NOW, updated_at=_NOW)


def _patch_users(h, monkeypatch, rows, total):
    users = MagicMock(search=MagicMock(return_value=rows), count_search=MagicMock(return_value=total))
    monkeypatch.setattr(h, "Users", users)
    return users


def test_get_user_list_paginated_shape(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    users = _patch_users(h, monkeypatch, [_user(1), _user(2)], total=45)

    resp = h.handler(_event({"search": "ana", "page": 3, "page_size": 10}), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["count"] == 2
    assert body["pagination"] == {"offset": 20, "limit": 10, "total": 45}
    assert body["results"][0] == {
        "id": "u-1", "email": "u1@x.co", "full_name": "User 1",
        "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
    }
    users.search.assert_called_once_with("ana", 10, 20)
    users.count_search.assert_called_once_with("ana")


def test_get_user_list_defaults_without_body(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    users = _patch_users(h, monkeypatch, [], total=0)

    resp = h.handler(_event(), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {
        "results": [], "count": 0, "pagination": {"offset": 0, "limit": 20, "total": 0},
    }
    users.search.assert_called_once_with("", 20, 0)


def test_get_user_list_search_is_trimmed_and_accepts_query_string(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    users = _patch_users(h, monkeypatch, [], total=0)

    h.handler(_event(query={"search": "  ana  ", "page": "2", "page_size": "5"}), None)

    users.search.assert_called_once_with("ana", 5, 5)


def test_get_user_list_rejects_bad_pagination(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    users = _patch_users(h, monkeypatch, [], total=0)

    for body, error in (
        ({"page": 0}, "invalid_page"),
        ({"page": "x"}, "invalid_page"),
        ({"page_size": 0}, "invalid_page_size"),
        ({"page_size": 101}, "invalid_page_size"),
        ({"search": 5}, "invalid_search"),
    ):
        resp = h.handler(_event(body), None)

        assert resp["statusCode"] == 400, body
        assert json.loads(resp["body"]) == {"error": error}
    users.search.assert_not_called()


def test_get_user_list_user_token_is_rejected(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr("libs.utils.auth.AdminBearerTokens", MagicMock(get_by_hash=MagicMock(return_value=None)))
    users = _patch_users(h, monkeypatch, [], total=0)

    resp = h.handler(_event(), None)

    assert resp["statusCode"] == 401
    users.search.assert_not_called()


def test_get_user_list_requires_auth(load_handler):
    h = load_handler(__file__)

    resp = h.handler({"headers": {}}, None)

    assert resp["statusCode"] == 401
