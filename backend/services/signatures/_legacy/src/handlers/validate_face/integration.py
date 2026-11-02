"""Deploy-verification tests for signatures/validate_face.

Two variants:

  * Sad path (always runs): uploads a solid-color PNG with zero
    faces; asserts Rekognition detects nothing and the handler
    returns 422.

  * Happy path (skipped unless SIGNATURES_TEST_FACE_PATH points to
    a real face JPEG): uploads the fixture and asserts the row is
    marked validated.

The Rekognition service can't be faked with synthetic pixels, so the
happy path requires a real photo. The `bootstrap-signatures-v2.sh`
docs describe how to provide one.
"""
from __future__ import annotations

import pytest
import requests

from tests.integration_helpers import query_one
from tests.integration_signatures import (
    load_face_fixture,
    make_faceless_png,
    open_ceremony,
    signatures_api,
    upload_evidence,
    validate_face,
)

pytestmark = pytest.mark.integration


def test_validate_face_sad_path_no_face_detected():
    """Solid-color PNG must produce 422 face_not_found. Row must NOT
    be marked validated."""
    ctx = open_ceremony(signer_name="ITest ValidateFace NoFace")
    try:
        upload_evidence(ctx, "face", make_faceless_png(), "image/png")
        resp = requests.post(
            f"{signatures_api()}/signatures/{ctx.sign_id}/evidence/face",
            timeout=60,
        )
        assert resp.status_code == 422, resp.text
        # Error code should mention "face" -- either face_not_found or
        # face_invalid_*; both are correct signals.
        err = resp.json().get("error", "")
        assert "face" in err.lower(), err
        row = query_one(
            "SELECT face_validated_at FROM signatures WHERE sign_id = :s",
            s=ctx.sign_id,
        )
        assert row is not None and row["face_validated_at"] is None
    finally:
        ctx.close()


def test_validate_face_happy_path_when_fixture_present():
    """If a real face fixture is configured, upload it and assert the
    handler validates it (Rekognition detects the face + confidence
    high + eyes open per EYES_OPEN attribute)."""
    face = load_face_fixture()
    if face is None:
        pytest.skip(
            "Set SIGNATURES_TEST_FACE_PATH to a real face JPEG to run "
            "the validate_face happy path."
        )
    ctx = open_ceremony(signer_name="ITest ValidateFace Happy")
    try:
        upload_evidence(ctx, "face", face, "image/jpeg")
        resp = validate_face(ctx)
        # Response shape is {sign_id, stage}. DB is the source of truth.
        assert resp["sign_id"] == ctx.sign_id
        row = query_one(
            "SELECT face_validated_at FROM signatures WHERE sign_id = :s",
            s=ctx.sign_id,
        )
        assert row is not None and row["face_validated_at"] is not None
    finally:
        ctx.close()


def test_validate_face_requires_uploaded_evidence():
    """Calling validate before uploading returns 404 evidence_missing."""
    ctx = open_ceremony(signer_name="ITest ValidateFace NoEvidence")
    try:
        resp = requests.post(
            f"{signatures_api()}/signatures/{ctx.sign_id}/evidence/face",
            timeout=30,
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"] == "evidence_missing"
    finally:
        ctx.close()
