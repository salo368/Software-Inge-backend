"""Deploy-verification tests for signatures/request_otp.

Exercises both:

  * The public contract (issue an OTP, hash lands in DB, plaintext
    NEVER in the standard response).
  * The debug hatch (with a valid HMAC header the plaintext appears
    under `_debug_otp`). This is the mechanism the rest of the
    integration suite uses to complete ceremonies.
"""
from __future__ import annotations

import pytest
import requests

from tests.integration_helpers import query_one
from tests.integration_signatures import (
    drive_to_stage,
    hmac_sign_id,
    load_face_fixture,
    open_ceremony,
    request_otp_with_debug_disclosure,
    signatures_api,
)

pytestmark = pytest.mark.integration


def test_request_otp_stores_hash_and_hides_plaintext():
    """Standard call (no debug header): response omits plaintext, DB
    stores a fresh SHA-256 hash + expires_at, stage advances to 'otp'."""
    face = load_face_fixture()
    if face is None:
        pytest.skip("SIGNATURES_TEST_FACE_PATH not set")
    ctx = open_ceremony(signer_name="ITest RequestOTP")
    try:
        drive_to_stage(ctx, "consent", face_bytes=face)

        # Standard call: no debug header.
        resp = requests.post(
            f"{signatures_api()}/signatures/{ctx.sign_id}/otp",
            timeout=30,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["stage"] == "otp"
        assert "_debug_otp" not in body  # secrecy
        assert body["otp"]["expires_at"]

        row = query_one(
            "SELECT stage, otp_hash, otp_expires_at, otp_attempts "
            "FROM signatures WHERE sign_id = :s",
            s=ctx.sign_id,
        )
        assert row["stage"] == "otp"
        assert row["otp_hash"] and len(row["otp_hash"]) == 64  # sha256 hex
        assert row["otp_expires_at"] is not None
        assert row["otp_attempts"] == 0
    finally:
        ctx.close()


def test_request_otp_debug_header_discloses_plaintext():
    """With a valid HMAC header the response includes the plaintext.
    This is what every downstream integration test depends on."""
    face = load_face_fixture()
    if face is None:
        pytest.skip("SIGNATURES_TEST_FACE_PATH not set")
    ctx = open_ceremony(signer_name="ITest RequestOTP Debug")
    try:
        drive_to_stage(ctx, "consent", face_bytes=face)
        plaintext = request_otp_with_debug_disclosure(ctx)
        # 6-digit numeric OTP.
        assert plaintext.isdigit() and len(plaintext) == 6, plaintext
    finally:
        ctx.close()


def test_request_otp_wrong_hmac_does_not_disclose():
    """Sending a bogus HMAC value must NOT leak the plaintext, even
    with the debug key provisioned in dev. Constant-time compare
    rejects, response omits `_debug_otp`."""
    face = load_face_fixture()
    if face is None:
        pytest.skip("SIGNATURES_TEST_FACE_PATH not set")
    ctx = open_ceremony(signer_name="ITest RequestOTP WrongHMAC")
    try:
        drive_to_stage(ctx, "consent", face_bytes=face)
        resp = requests.post(
            f"{signatures_api()}/signatures/{ctx.sign_id}/otp",
            headers={"X-Debug-OTP-Signature": "deadbeef" * 8},  # 64 hex chars
            timeout=30,
        )
        assert resp.status_code == 200, resp.text
        assert "_debug_otp" not in resp.json()
    finally:
        ctx.close()


def test_request_otp_rejected_without_consent():
    """Before consent, request_otp returns 409 (stage guard)."""
    ctx = open_ceremony(signer_name="ITest RequestOTP NoConsent")
    try:
        resp = requests.post(
            f"{signatures_api()}/signatures/{ctx.sign_id}/otp", timeout=15
        )
        assert resp.status_code == 409, resp.text
    finally:
        ctx.close()
