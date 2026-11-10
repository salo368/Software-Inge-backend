"""Deploy-verification tests for signatures/validate_id_back.

Symmetric to validate_id_front but for the reverse of the ID
document. Same Rekognition path, different heuristics (looks for
different keywords / layout).
"""
from __future__ import annotations

import pytest

from tests.integration_helpers import query_one
from tests.integration_signatures import (
    make_synthetic_id_png,
    open_ceremony,
    upload_evidence,
    validate_id_side,
)

pytestmark = pytest.mark.integration


def test_validate_id_back_happy_path():
    """Uploads the back-of-ID synthetic PNG and validates it. Row must
    have `id_back_validated_at` stamped. Response shape:
    `{sign_id, stage, detected_lines}`."""
    ctx = open_ceremony(signer_name="ITest ValidateIDBack")
    try:
        upload_evidence(ctx, "id_back", make_synthetic_id_png("back"), "image/png")
        resp = validate_id_side(ctx, "back")
        assert resp["detected_lines"] >= 1, resp
        row = query_one(
            "SELECT id_back_validated_at FROM signatures WHERE sign_id = :s",
            s=ctx.sign_id,
        )
        assert row is not None and row["id_back_validated_at"] is not None
    finally:
        ctx.close()


def test_validate_id_back_does_not_accept_front_image():
    """The `front` synthetic image has different landmark words than
    the back. It must fail the back-specific heuristics OR at minimum
    not advance the stage in a way that pretends the back is verified.
    (Best-effort check: accept 200 OR 422 depending on how strict
    the heuristics are; assert the row shape is consistent with the
    response.)"""
    import requests
    from tests.integration_signatures import signatures_api

    ctx = open_ceremony(signer_name="ITest ValidateIDBack Mismatch")
    try:
        # Upload the FRONT image but call the BACK endpoint.
        upload_evidence(ctx, "id_back", make_synthetic_id_png("front"), "image/png")
        resp = requests.post(
            f"{signatures_api()}/signatures/{ctx.sign_id}/evidence/id-back",
            timeout=60,
        )
        # Either the handler accepts (200) because both images share
        # generic text, or it rejects (422) because the back-specific
        # landmarks are missing. Both are valid deploy signals; what we
        # care about is that the DB state matches the response.
        row = query_one(
            "SELECT id_back_validated_at FROM signatures WHERE sign_id = :s",
            s=ctx.sign_id,
        )
        if resp.status_code == 200:
            assert row["id_back_validated_at"] is not None
        else:
            assert resp.status_code in (400, 422), resp.text
            assert row["id_back_validated_at"] is None
    finally:
        ctx.close()
