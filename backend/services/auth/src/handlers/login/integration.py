"""Deploy-verification tests for auth/login.

Verifies that logging in with a real user issues a bearer_tokens row and
that /auth/me accepts the returned token, all against the deployed dev
stack. Gated by --integration (see backend/conftest.py).
"""
from __future__ import annotations

import pytest
import requests

from tests.integration_helpers import (
    api_base,
    bearer,
    cleanup_user,
    query_scalar,
    signup_and_login,
)

pytestmark = pytest.mark.integration


def test_login_returns_a_new_bearer_token_row():
    """Registrar + hacer logout implícito no está en scope; validamos que
    cada login sucesivo agrega un token vivo distinto en la tabla."""
    session = signup_and_login()
    email = session["email"]
    base = api_base("auth")

    try:
        # Debe haber 1 token vivo tras el registro.
        assert query_scalar(
            "SELECT COUNT(*) FROM bearer_tokens WHERE user_id = :u AND revoked_at IS NULL",
            u=session["user_id"],
        ) == 1

        # Un login extra debe agregar otro token vivo (no reciclar).
        resp = requests.post(
            f"{base}/auth/login",
            json={"email": email, "password": session["password"]},
            timeout=15,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["token"] and body["token"] != session["token"]

        assert query_scalar(
            "SELECT COUNT(*) FROM bearer_tokens WHERE user_id = :u AND revoked_at IS NULL",
            u=session["user_id"],
        ) == 2

        # Los dos tokens sirven contra /auth/me.
        for tok in (session["token"], body["token"]):
            me = requests.get(f"{base}/auth/me", headers=bearer(tok), timeout=15)
            assert me.status_code == 200, me.text
            assert me.json()["user"]["email"] == email
    finally:
        cleanup_user(email)


def test_login_wrong_password_does_not_issue_a_token():
    """El endpoint responde 401 y ninguna fila nueva aparece en bearer_tokens."""
    session = signup_and_login()
    base = api_base("auth")

    try:
        tokens_before = query_scalar(
            "SELECT COUNT(*) FROM bearer_tokens WHERE user_id = :u",
            u=session["user_id"],
        )
        resp = requests.post(
            f"{base}/auth/login",
            json={"email": session["email"], "password": "wrong-password"},
            timeout=15,
        )
        assert resp.status_code == 401
        assert resp.json() == {"error": "invalid_credentials"}

        tokens_after = query_scalar(
            "SELECT COUNT(*) FROM bearer_tokens WHERE user_id = :u",
            u=session["user_id"],
        )
        assert tokens_before == tokens_after, \
            "login con password inválido no debe emitir token"
    finally:
        cleanup_user(session["email"])
