"""Deploy-verification tests for auth/register.

Runs post-deploy against the real dev API + real Postgres to prove not just
that the endpoint answers, but that the user actually landed in the users
table with a valid bcrypt hash, and that a bearer token was persisted.

Gated by --integration (see backend/conftest.py). See docs/repo-structure.md §13.3.
"""
from __future__ import annotations

import pytest
import requests

from tests.integration_helpers import (
    api_base,
    bearer,
    cleanup_user,
    query_one,
    query_scalar,
    unique_email,
)

pytestmark = pytest.mark.integration


def test_register_persists_user_and_token_in_db():
    """Fuente de reposo: la fila del usuario debe existir en Postgres tras
    el POST, y el hash debe ser bcrypt real (no plaintext)."""
    email = unique_email()
    password = "hunter22aa"
    payload = {"email": email, "password": password, "full_name": "Integration Bot"}
    base = api_base("auth")

    try:
        # 1) Contract check: mismo assert style que el unit test.
        resp = requests.post(f"{base}/auth/register", json=payload, timeout=15)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["user"]["email"] == email
        assert body["user"]["full_name"] == "Integration Bot"
        assert body["token"]
        assert body["expires_at"]

        # 2) Fuente de reposo #1: la fila users existe con el hash correcto.
        row = query_one(
            "SELECT id, email, password_hash, full_name FROM users WHERE email = :e",
            e=email,
        )
        assert row is not None, f"no users row for {email}"
        assert row["email"] == email
        # bcrypt hashes start with $2a$, $2b$ o $2y$ (12 rounds -> $2b$12$...).
        assert row["password_hash"].startswith("$2"), \
            f"password_hash does not look like bcrypt: {row['password_hash'][:10]}"
        assert row["password_hash"] != password  # obvio, pero explícito

        # 3) Fuente de reposo #2: el bearer token quedó registrado y activo.
        active_tokens = query_scalar(
            "SELECT COUNT(*) FROM bearer_tokens "
            "WHERE user_id = :u AND revoked_at IS NULL",
            u=row["id"],
        )
        assert active_tokens == 1

        # 4) El token devuelto abre /auth/me contra la misma infra.
        me = requests.get(f"{base}/auth/me", headers=bearer(body["token"]), timeout=15)
        assert me.status_code == 200
        assert me.json()["user"]["email"] == email
    finally:
        cleanup_user(email)


def test_register_rejects_duplicate_email_in_db():
    """Aunque el primer registro sí persistió, el segundo con el mismo email
    debe devolver 409 sin crear una segunda fila."""
    email = unique_email()
    payload = {"email": email, "password": "hunter22aa", "full_name": "Dup Bot"}
    base = api_base("auth")

    try:
        first = requests.post(f"{base}/auth/register", json=payload, timeout=15)
        assert first.status_code == 201, first.text

        second = requests.post(f"{base}/auth/register", json=payload, timeout=15)
        assert second.status_code == 409
        assert second.json() == {"error": "email_taken"}

        # Fuente de reposo: sigue habiendo EXACTAMENTE una fila.
        count = query_scalar("SELECT COUNT(*) FROM users WHERE email = :e", e=email)
        assert count == 1
    finally:
        cleanup_user(email)
