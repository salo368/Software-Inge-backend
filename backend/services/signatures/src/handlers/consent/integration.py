"""Deploy-verification tests for signatures/consent.

The consent step records explicit acknowledgment of Ley 527 terms.
Gates the transition 'identity' -> 'consent'. This test exercises
the endpoint against a real dev ceremony that has already been
driven to 'identity' via the helper.
"""
from __future__ import annotations

import pytest
import requests

from tests.integration_helpers import query_one
from tests.integration_signatures import (
    drive_to_stage,
    give_consent,
    load_face_fixture,
    open_ceremony,
    signatures_api,
)

pytestmark = pytest.mark.integration


def test_consent_records_timestamp_and_advances_stage():
    """After consent, `consent_given_at` is stamped, terms_version is
    persisted, and stage advances to 'consent'."""
    face = load_face_fixture()
    if face is None:
        pytest.skip(
            "SIGNATURES_TEST_FACE_PATH not set; consent requires an "
            "'identity' ceremony which needs a valid face."
        )
    ctx = open_ceremony(signer_name="ITest Consent")
    try:
        drive_to_stage(ctx, "identity", face_bytes=face)
        resp = give_consent(ctx, terms_version="ley-527-v1")
        assert resp["stage"] == "consent"

        row = query_one(
            "SELECT consent_given_at, consent_terms_version, stage "
            "FROM signatures WHERE sign_id = :s",
            s=ctx.sign_id,
        )
        assert row["consent_given_at"] is not None
        assert row["consent_terms_version"] == "ley-527-v1"
        assert row["stage"] == "consent"
    finally:
        ctx.close()


def test_consent_rejects_without_terms_version():
    """`terms_version` is required; the handler must 400 without it."""
    ctx = open_ceremony(signer_name="ITest Consent NoTerms")
    try:
        # We don't drive to identity because the guard we're testing
        # runs BEFORE stage checks.
        resp = requests.post(
            f"{signatures_api()}/signatures/{ctx.sign_id}/consent",
            json={},
            timeout=15,
        )
        assert resp.status_code == 400, resp.text
    finally:
        ctx.close()


def test_consent_rejected_before_identity_stage():
    """Consent can only be given AFTER the identity stage. A freshly
    created ceremony (stage='created') must be rejected with 409."""
    ctx = open_ceremony(signer_name="ITest Consent WrongStage")
    try:
        resp = requests.post(
            f"{signatures_api()}/signatures/{ctx.sign_id}/consent",
            json={"terms_version": "v1"},
            timeout=15,
        )
        assert resp.status_code == 409, resp.text
        # Row should NOT be marked consented.
        row = query_one(
            "SELECT consent_given_at FROM signatures WHERE sign_id = :s",
            s=ctx.sign_id,
        )
        assert row["consent_given_at"] is None
    finally:
        ctx.close()
