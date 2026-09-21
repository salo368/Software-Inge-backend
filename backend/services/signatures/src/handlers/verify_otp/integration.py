"""Deploy-verification tests for signatures/verify_otp.

Exercises the OTP comparison + attempt counter + downstream trigger
of the async `sign` lambda. Uses the debug hatch (PR #65) to obtain
the plaintext OTP without a human.

Depends on: valid face fixture (to reach 'consent' stage).
"""
from __future__ import annotations

import pytest
import requests

from tests.integration_helpers import query_one
from tests.integration_signatures import (
    drive_to_stage,
    load_face_fixture,
    open_ceremony,
    request_otp_with_debug_disclosure,
    signatures_api,
    verify_otp,
)

pytestmark = pytest.mark.integration


def test_verify_otp_happy_path_advances_stage_to_signing():
    """Correct OTP -> stage advances to 'signing' and the async `sign`
    lambda gets invoked. We don't wait for it here (that's covered by
    sign/integration.py) -- just assert the transition happened."""
    face = load_face_fixture()
    if face is None:
        pytest.skip("SIGNATURES_TEST_FACE_PATH not set")
    ctx = open_ceremony(signer_name="ITest VerifyOTP")
    try:
        drive_to_stage(ctx, "consent", face_bytes=face)
        plaintext = request_otp_with_debug_disclosure(ctx)
        resp = verify_otp(ctx, plaintext)
        assert resp["stage"] in ("signing", "signed"), resp
        # DB reflects the transition.
        row = query_one(
            "SELECT stage FROM signatures WHERE sign_id = :s", s=ctx.sign_id
        )
        assert row["stage"] in ("signing", "signed")
    finally:
        ctx.close()


def test_verify_otp_wrong_code_increments_attempts():
    """Wrong OTP -> 401 and otp_attempts increments. Row stays in
    'otp' stage."""
    face = load_face_fixture()
    if face is None:
        pytest.skip("SIGNATURES_TEST_FACE_PATH not set")
    ctx = open_ceremony(signer_name="ITest VerifyOTP Wrong")
    try:
        drive_to_stage(ctx, "consent", face_bytes=face)
        # Issue an OTP but verify with a WRONG code.
        request_otp_with_debug_disclosure(ctx)
        resp = requests.post(
            f"{signatures_api()}/signatures/{ctx.sign_id}/otp/verify",
            json={"code": "000000"},  # deterministic wrong value
            timeout=15,
        )
        assert resp.status_code in (401, 422), resp.text
        row = query_one(
            "SELECT stage, otp_attempts FROM signatures WHERE sign_id = :s",
            s=ctx.sign_id,
        )
        assert row["stage"] == "otp"
        assert row["otp_attempts"] >= 1
    finally:
        ctx.close()


def test_verify_otp_rejects_before_request():
    """No OTP requested yet -> 409 (or 400). Row is untouched."""
    ctx = open_ceremony(signer_name="ITest VerifyOTP NoRequest")
    try:
        resp = requests.post(
            f"{signatures_api()}/signatures/{ctx.sign_id}/otp/verify",
            json={"code": "123456"},
            timeout=15,
        )
        assert resp.status_code in (400, 409), resp.text
    finally:
        ctx.close()
