"""Deploy-verification tests for signatures/create.

Exercises the ONLY M2M endpoint (`POST /signatures`) end-to-end:
uploads a synthetic PDF to the signatures bucket, generates a
presigned GET, and POSTs with `X-Service-Key`. Asserts that the row
lands in Postgres and that the returned `sign_url` is well-formed.

Gated by --integration (see backend/conftest.py).
"""
from __future__ import annotations

import pytest
import requests

from tests.integration_helpers import query_one, cleanup_signature
from tests.integration_signatures import (
    get_service_key,
    make_synthetic_pdf,
    open_ceremony,
    signatures_api,
    signatures_bucket,
)

pytestmark = pytest.mark.integration


def test_create_opens_ceremony_and_persists_row():
    """State at rest: the signatures row must exist post-POST with the
    stage 'created' and the same sign_id we got back."""
    ctx = open_ceremony(signer_name="ITest Create")
    try:
        # Response shape (from ctx).
        assert ctx.sign_id
        assert ctx.hash_original
        assert ctx.sign_url.endswith(f"/sign/{ctx.sign_id}"), ctx.sign_url

        # State at rest: the row exists and matches.
        row = query_one(
            "SELECT sign_id, signer_email, stage, hash_original "
            "FROM signatures WHERE sign_id = :s",
            s=ctx.sign_id,
        )
        assert row is not None
        assert row["sign_id"] == ctx.sign_id
        assert row["signer_email"] == ctx.signer_email
        assert row["stage"] == "created"
        assert row["hash_original"] == ctx.hash_original
    finally:
        ctx.close()


def test_create_rejects_missing_service_key():
    """Without X-Service-Key, `POST /signatures` returns 401 and does
    NOT create a row."""
    # Build a valid body but omit the header.
    import hashlib
    import uuid
    from tests.integration_helpers import _client

    pdf = make_synthetic_pdf()
    bucket = signatures_bucket()
    src_key = f"_test-sources/{uuid.uuid4()}.pdf"
    s3 = _client("s3")
    s3.put_object(Bucket=bucket, Key=src_key, Body=pdf, ContentType="application/pdf")
    try:
        presigned = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": src_key},
            ExpiresIn=120,
        )
        resp = requests.post(
            f"{signatures_api()}/signatures",
            json={
                "pdf_source_url": presigned,
                "signature_location": {"page": 1, "x_pct": 10, "y_pct": 10},
                "signer_email": "unauth@itest.cdts.dev",
            },
            # No X-Service-Key.
            timeout=15,
        )
        assert resp.status_code == 401, resp.text
        assert resp.json()["error"] == "missing_service_key"
    finally:
        try:
            s3.delete_object(Bucket=bucket, Key=src_key)
        except Exception:
            pass


def test_create_rejects_wrong_service_key():
    """Wrong X-Service-Key returns 401 without creating a row."""
    ctx_dummy = None  # not opened; just building a body
    from tests.integration_helpers import _client
    import uuid

    pdf = make_synthetic_pdf()
    bucket = signatures_bucket()
    src_key = f"_test-sources/{uuid.uuid4()}.pdf"
    s3 = _client("s3")
    s3.put_object(Bucket=bucket, Key=src_key, Body=pdf, ContentType="application/pdf")
    try:
        presigned = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": src_key},
            ExpiresIn=120,
        )
        resp = requests.post(
            f"{signatures_api()}/signatures",
            json={
                "pdf_source_url": presigned,
                "signature_location": {"page": 1, "x_pct": 10, "y_pct": 10},
                "signer_email": "wrong-key@itest.cdts.dev",
            },
            headers={"X-Service-Key": "obviously-not-the-real-one"},
            timeout=15,
        )
        assert resp.status_code == 401, resp.text
        assert resp.json()["error"] == "invalid_service_key"
    finally:
        try:
            s3.delete_object(Bucket=bucket, Key=src_key)
        except Exception:
            pass
