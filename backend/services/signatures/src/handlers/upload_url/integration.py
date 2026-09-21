"""Deploy-verification tests for signatures/upload_url.

Verifies that the presigned URL returned by
`POST /signatures/{sign_id}/upload-url` is actually usable to PUT
evidence to the signatures bucket, and that the S3 key the handler
computes matches the ceremony's expected path.
"""
from __future__ import annotations

import pytest
import requests

from tests.integration_helpers import s3_head
from tests.integration_signatures import (
    make_synthetic_id_png,
    open_ceremony,
    signatures_api,
    signatures_bucket,
    upload_evidence,
)

pytestmark = pytest.mark.integration


def test_upload_url_returns_working_presigned_put():
    """PUT to the presigned URL succeeds and the object is readable
    at the returned key. This proves both the handler's key layout
    and the presign IAM scope."""
    ctx = open_ceremony(signer_name="ITest UploadUrl")
    try:
        body = make_synthetic_id_png("front")
        key = upload_evidence(ctx, "id_front", body, "image/png")
        # Key convention (see upload_url handler `_EVIDENCE_MAP`):
        # id_front -> prefix `id/front`, so full key is
        # transactions/{sign_id}/id/front.{ext}
        assert key.startswith(f"transactions/{ctx.sign_id}/id/front"), key
        head = s3_head(signatures_bucket(), key)
        assert head is not None, f"object missing at {key!r}"
        assert head["ContentType"] in ("image/png", "binary/octet-stream")
        # Same order of magnitude as the body we uploaded (S3 metadata).
        assert head["ContentLength"] == len(body)
    finally:
        ctx.close()


def test_upload_url_rejects_unknown_evidence_type():
    """Unknown evidence_type returns 400."""
    ctx = open_ceremony(signer_name="ITest UploadUrl Bad")
    try:
        resp = requests.post(
            f"{signatures_api()}/signatures/{ctx.sign_id}/upload-url",
            json={"evidence_type": "not_a_real_type", "content_type": "image/png"},
            timeout=15,
        )
        assert resp.status_code == 400, resp.text
        assert resp.json()["error"] == "invalid_evidence_type"
    finally:
        ctx.close()


def test_upload_url_returns_404_for_unknown_sign_id():
    """Any endpoint that takes sign_id in path returns 404 for a
    non-existent one. Confirms `require_sign_id` is wired."""
    resp = requests.post(
        f"{signatures_api()}/signatures/nonexistent-sign-id/upload-url",
        json={"evidence_type": "id_front", "content_type": "image/png"},
        timeout=15,
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error"] == "signature_not_found"
