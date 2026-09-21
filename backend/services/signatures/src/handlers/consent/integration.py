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
    persisted, and stage advances from 'identity' to 'consent'.

    Uses `v1.0` because the handler's `_KNOWN_TERMS_VERSIONS` accepts
    only that value today; unknown versions get 400.
    """
    face = load_face_fixture()
    if face is None:
        pytest.skip(
            "SIGNATURES_TEST_FACE_PATH not set; consent requires an "
            "'identity' ceremony which needs a valid face."
        )
    ctx = open_ceremony(signer_name="ITest Consent")
    try:
        drive_to_stage(ctx, "identity", face_bytes=face)
        resp = give_consent(ctx, terms_version="v1.0")
        assert resp["stage"] == "consent"

        row = query_one(
            "SELECT consent_given_at, consent_terms_version, stage "
            "FROM signatures WHERE sign_id = :s",
            s=ctx.sign_id,
        )
        assert row["consent_given_at"] is not None
        assert row["consent_terms_version"] == "v1.0"
        assert row["stage"] == "consent"
    finally:
        ctx.close()


def test_consent_rejects_wrong_stage_before_body_validation():
    """The stage guard fires BEFORE body validation, so a bad body on a
    freshly created ceremony yields 409 (stage_not_allowed_current_created),
    not 400. This documents the ordering of the two checks.
    """
    ctx = open_ceremony(signer_name="ITest Consent BadStage")
    try:
        resp = requests.post(
            f"{signatures_api()}/signatures/{ctx.sign_id}/consent",
            json={},  # missing terms_version, but stage guard fires first
            timeout=15,
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["error"].startswith("stage_not_allowed_current_")
    finally:
        ctx.close()


def test_consent_rejects_unknown_terms_version():
    """When the ceremony IS at a stage that allows consent, an unknown
    `terms_version` must return 400 unknown_terms_version. Requires a
    face fixture to reach the identity stage."""
    face = load_face_fixture()
    if face is None:
        pytest.skip("SIGNATURES_TEST_FACE_PATH not set")
    ctx = open_ceremony(signer_name="ITest Consent BadVersion")
    try:
        drive_to_stage(ctx, "identity", face_bytes=face)
        resp = requests.post(
            f"{signatures_api()}/signatures/{ctx.sign_id}/consent",
            json={"terms_version": "not-a-real-version"},
            timeout=15,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["error"] == "unknown_terms_version"
        # Row must NOT be marked consented.
        row = query_one(
            "SELECT consent_given_at FROM signatures WHERE sign_id = :s",
            s=ctx.sign_id,
        )
        assert row["consent_given_at"] is None
    finally:
        ctx.close()
