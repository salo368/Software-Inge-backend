"""Deploy-verification tests for signatures/register_signature.

`register_signature` is the "commit" step for the drawn signature
PNG: the presigned PUT already stored the bytes, this handler
stamps the `signature_key` on the row (there is no cryptographic
validation for the drawing itself).

It also advances stage to 'consent' when all 4 evidences are ready
(3 biometric validated + drawn signature uploaded).
"""
from __future__ import annotations

import pytest
import requests

from tests.integration_helpers import query_one
from tests.integration_signatures import (
    load_face_fixture,
    make_synthetic_id_png,
    make_synthetic_signature_png,
    open_ceremony,
    register_signature_drawing,
    signatures_api,
    upload_evidence,
    validate_id_side,
    validate_face,
)

pytestmark = pytest.mark.integration


def test_register_signature_stamps_signature_key():
    """After the PUT + register call, the row has signature_key set."""
    ctx = open_ceremony(signer_name="ITest RegisterSignature")
    try:
        upload_evidence(
            ctx, "signature", make_synthetic_signature_png(), "image/png"
        )
        register_signature_drawing(ctx)
        row = query_one(
            "SELECT signature_key FROM signatures WHERE sign_id = :s",
            s=ctx.sign_id,
        )
        assert row is not None and row["signature_key"] is not None
        assert row["signature_key"].startswith(
            f"transactions/{ctx.sign_id}/signature"
        )
    finally:
        ctx.close()


def test_register_signature_advances_stage_when_all_evidences_ready():
    """Advances 'created' -> 'identity' when the 3 biometric evidences
    are validated AND the drawn signature is uploaded+registered.

    Only runs when a face fixture is provided; without it the ceremony
    can't reach the "all evidences ready" state.
    """
    face = load_face_fixture()
    if face is None:
        pytest.skip("SIGNATURES_TEST_FACE_PATH not set")

    ctx = open_ceremony(signer_name="ITest RegisterSignature FullFlow")
    try:
        upload_evidence(ctx, "id_front", make_synthetic_id_png("front"), "image/png")
        validate_id_side(ctx, "front")
        upload_evidence(ctx, "id_back", make_synthetic_id_png("back"), "image/png")
        validate_id_side(ctx, "back")
        upload_evidence(ctx, "face", face, "image/jpeg")
        validate_face(ctx)
        # Now the drawing.
        upload_evidence(
            ctx, "signature", make_synthetic_signature_png(), "image/png"
        )
        resp = register_signature_drawing(ctx)
        assert resp.get("stage") == "identity", resp
    finally:
        ctx.close()


def test_register_signature_requires_uploaded_drawing():
    """Calling register without first uploading the PNG returns 4xx."""
    ctx = open_ceremony(signer_name="ITest RegisterSignature NoUpload")
    try:
        resp = requests.post(
            f"{signatures_api()}/signatures/{ctx.sign_id}/evidence/signature",
            timeout=30,
        )
        assert resp.status_code in (400, 409), resp.text
    finally:
        ctx.close()
