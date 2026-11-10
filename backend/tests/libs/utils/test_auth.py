"""Unit tests for `libs.utils.auth`: explicit auth types for require_auth
and issue_token, user vs internal (admin) tokens in separate tables."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from libs.core.responses import HandledError
from libs.utils import auth


def _event(token="tok"):
    return {"headers": {"Authorization": f"Bearer {token}"}}


def _patch_tables(monkeypatch, *, user_bearer=None, admin_bearer=None, user=None, admin=None):
    tables = dict(
        UserBearerTokens=MagicMock(get_by_hash=MagicMock(return_value=user_bearer), create=MagicMock()),
        AdminBearerTokens=MagicMock(get_by_hash=MagicMock(return_value=admin_bearer), create=MagicMock()),
        Users=MagicMock(get_by_id=MagicMock(return_value=user)),
        Admins=MagicMock(get_by_id=MagicMock(return_value=admin)),
    )
    for name, mock in tables.items():
        monkeypatch.setattr(auth, name, mock)
    monkeypatch.setattr(auth, "is_alive", MagicMock(return_value=True))
    return tables


def _protected(auth_type):
    @auth.require_auth(auth_type)
    def handler(event, context):
        return event
    return handler


def test_user_token_on_user_endpoint(monkeypatch):
    bearer = MagicMock(revoked_at=None, user_id="u-1")
    user = MagicMock(id="u-1")
    tables = _patch_tables(monkeypatch, user_bearer=bearer, user=user)

    event = _protected(auth.AuthsTypes.USER)(_event(), None)

    assert event["user"] is user
    assert event["token"] is bearer
    assert "admin" not in event
    tables["Users"].get_by_id.assert_called_once_with("u-1")
    tables["AdminBearerTokens"].get_by_hash.assert_not_called()


def test_admin_token_on_internal_endpoint(monkeypatch):
    bearer = MagicMock(revoked_at=None, admin_id="a-1")
    admin = MagicMock(id="a-1")
    tables = _patch_tables(monkeypatch, admin_bearer=bearer, admin=admin)

    event = _protected(auth.AuthsTypes.INTERNAL)(_event(), None)

    assert event["admin"] is admin
    assert event["token"] is bearer
    assert "user" not in event
    tables["Admins"].get_by_id.assert_called_once_with("a-1")
    tables["UserBearerTokens"].get_by_hash.assert_not_called()


def test_user_token_is_rejected_on_internal_endpoint(monkeypatch):
    # A user token only exists in user_bearer_tokens, so the admin lookup misses.
    _patch_tables(monkeypatch, user_bearer=MagicMock(revoked_at=None, user_id="u-1"), admin_bearer=None)

    with pytest.raises(HandledError) as err:
        _protected(auth.AuthsTypes.INTERNAL)(_event(), None)

    assert (err.value.status_code, err.value.message) == (401, "invalid_or_expired_token")


def test_admin_token_is_rejected_on_user_endpoint(monkeypatch):
    _patch_tables(monkeypatch, user_bearer=None, admin_bearer=MagicMock(revoked_at=None, admin_id="a-1"))

    with pytest.raises(HandledError) as err:
        _protected(auth.AuthsTypes.USER)(_event(), None)

    assert (err.value.status_code, err.value.message) == (401, "invalid_or_expired_token")


def test_revoked_admin_token_is_rejected(monkeypatch):
    _patch_tables(monkeypatch, admin_bearer=MagicMock(revoked_at="2026-01-01", admin_id="a-1"), admin=MagicMock())

    with pytest.raises(HandledError) as err:
        _protected(auth.AuthsTypes.INTERNAL)(_event(), None)

    assert err.value.status_code == 401


def test_missing_header_is_rejected_before_any_lookup(monkeypatch):
    tables = _patch_tables(monkeypatch)

    with pytest.raises(HandledError) as err:
        _protected(auth.AuthsTypes.USER)({"headers": {}}, None)

    assert (err.value.status_code, err.value.message) == (401, "missing_bearer_token")
    tables["UserBearerTokens"].get_by_hash.assert_not_called()


def test_require_auth_without_type_fails_at_import_time():
    def handler(event, context):
        return event

    with pytest.raises(TypeError):
        auth.require_auth(handler)

    with pytest.raises(TypeError):
        auth.require_auth("USER")


def test_issue_token_stores_each_type_in_its_own_table(monkeypatch):
    tables = _patch_tables(monkeypatch)

    user_token, _ = auth.issue_token("u-1", auth.AuthsTypes.USER)
    admin_token, _ = auth.issue_token("a-1", auth.AuthsTypes.INTERNAL)

    user_args = tables["UserBearerTokens"].create.call_args.args
    admin_args = tables["AdminBearerTokens"].create.call_args.args
    assert user_args[:2] == ("u-1", auth._hash(user_token))
    assert admin_args[:2] == ("a-1", auth._hash(admin_token))
    assert tables["UserBearerTokens"].create.call_count == 1
    assert tables["AdminBearerTokens"].create.call_count == 1
