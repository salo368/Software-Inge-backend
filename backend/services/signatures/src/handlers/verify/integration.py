"""Deploy-verification tests for signatures/verify.

Public `POST /signatures/verify` endpoint. Contract (from
signatures-v2 §7 + handler code):

  Body:  {"pdf_source_url": "..."}  OR  {"sign_id": "..."}   (exactly one)
  Response 200:
    {
      "valid": bool,
      "document_integrity": bool,
      "signature_valid": bool,
      "certificate_valid": bool,
      "signer": {"email_masked": str|null, "name": str|null},
      "cert_serial": str|null,
      "signed_at": str|null,
      "reason": str|null,
      "ceremony": {sign_id_short, stage, ...} | null,
    }

Runs a full ceremony first to produce a real signed PDF, then hits
/verify in BOTH modes (sign_id and pdf_source_url) and asserts the
answers agree.
"""
from __future__ import annotations

import pytest
import requests

from tests.integration_helpers import _client
from tests.integration_signatures import (
    drive_to_stage,
    load_face_fixture,
    make_synthetic_pdf,
    open_ceremony,
    signatures_api,
    signatures_bucket,
)

pytestmark = pytest.mark.integration


def test_verify_by_sign_id_reports_intact_and_trusted():
    """After a full ceremony, /verify {sign_id} reports the PDF as
    intact + trusted, cert_serial and signer info populated."""
    face = load_face_fixture()
    if face is None:
        pytest.skip("SIGNATURES_TEST_FACE_PATH not set")

    ctx = open_ceremony(signer_name="ITest Verify BySignId")
    try:
        drive_to_stage(ctx, "signed", face_bytes=face)

        resp = requests.post(
            f"{signatures_api()}/signatures/verify",
            json={"sign_id": ctx.sign_id},
            timeout=60,
        )
        assert resp.status_code == 200, resp.text
        report = resp.json()

        # Cryptographic assertions -- the whole point of the endpoint.
        assert report["valid"] is True, report
        assert report["document_integrity"] is True, report
        assert report["signature_valid"] is True, report
        assert report["certificate_valid"] is True, report

        # Enriched ceremony context (only when sign_id was passed).
        assert report["ceremony"] is not None, report
        assert report["ceremony"]["sign_id_short"] == ctx.sign_id[:6]
        assert report["ceremony"]["stage"] == "signed"

        # Signer info surfaces from the leaf cert.
        assert report["cert_serial"]
        assert report["signer"]["name"] == "ITest Verify BySignId"
    finally:
        ctx.close()


def test_verify_by_pdf_source_url_matches_sign_id_variant():
    """Both `sign_id` and `pdf_source_url` modes must agree on the
    cryptographic verdict. This guards against a regression that
    would only affect one branch (e.g. the sign_id path reading a
    cached row vs. the URL path re-parsing bytes)."""
    face = load_face_fixture()
    if face is None:
        pytest.skip("SIGNATURES_TEST_FACE_PATH not set")

    ctx = open_ceremony(signer_name="ITest Verify ByURL")
    try:
        drive_to_stage(ctx, "signed", face_bytes=face)
        bucket = signatures_bucket()
        s3 = _client("s3")
        presigned = s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket,
                "Key": f"evidence-archive/{ctx.sign_id}/signed.pdf",
            },
            ExpiresIn=300,
        )
        r_url = requests.post(
            f"{signatures_api()}/signatures/verify",
            json={"pdf_source_url": presigned},
            timeout=60,
        )
        r_sign_id = requests.post(
            f"{signatures_api()}/signatures/verify",
            json={"sign_id": ctx.sign_id},
            timeout=60,
        )
        assert r_url.status_code == 200 and r_sign_id.status_code == 200

        b_url, b_sid = r_url.json(), r_sign_id.json()
        for field in (
            "valid",
            "document_integrity",
            "signature_valid",
            "certificate_valid",
            "cert_serial",
        ):
            assert b_url[field] == b_sid[field], (
                f"mismatch on {field}: url={b_url[field]!r} sign_id={b_sid[field]!r}"
            )
    finally:
        ctx.close()


def test_verify_rejects_unsigned_pdf():
    """An unsigned PDF must produce a report with signature_valid=False
    (or a 4xx). Never a 200 with valid=True."""
    import uuid

    bucket = signatures_bucket()
    key = f"_test-sources/{uuid.uuid4()}.pdf"
    pdf = make_synthetic_pdf(title="UNSIGNED PDF FOR VERIFY TEST")
    s3 = _client("s3")
    s3.put_object(Bucket=bucket, Key=key, Body=pdf, ContentType="application/pdf")
    try:
        presigned = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=120,
        )
        resp = requests.post(
            f"{signatures_api()}/signatures/verify",
            json={"pdf_source_url": presigned},
            timeout=60,
        )
        if resp.status_code == 200:
            body = resp.json()
            assert body["valid"] is False, body
            # An unsigned PDF has no signature to be "valid".
            assert body["signature_valid"] is False, body
        else:
            assert resp.status_code in (400, 422), resp.text
    finally:
        try:
            s3.delete_object(Bucket=bucket, Key=key)
        except Exception:
            pass


def test_verify_rejects_body_with_both_params():
    """The handler requires exactly one of `sign_id` or `pdf_source_url`;
    providing both must 400."""
    resp = requests.post(
        f"{signatures_api()}/signatures/verify",
        json={"sign_id": "whatever", "pdf_source_url": "https://x"},
        timeout=15,
    )
    assert resp.status_code == 400, resp.text
