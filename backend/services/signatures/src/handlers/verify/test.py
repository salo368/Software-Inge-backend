"""Unit tests for signatures/verify (public PAdES verification endpoint).

verify_pades_pdf is exercised end-to-end in test_mock_ca.py (real
cryptography roundtrip). Here we stub it out because the handler's job
is orchestration, not crypto:

    * choose the right source (URL vs sign_id) based on the body,
    * respect the payload cap,
    * enrich with ceremony context when we can,
    * mask PII in the response.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock


_STOCK_VERIFY_RESULT = {
    "valid": True,
    "document_integrity": True,
    "signature_valid": True,
    "certificate_valid": True,
    "signer_email": "signer@example.com",
    "signer_name": "Signer",
    "cert_serial": "c" * 32,
    "signed_at": "2026-09-21T00:00:00+00:00",
    "reason": None,
}


def _event(body: dict) -> dict:
    return {"body": json.dumps(body)}


def _make_row(**overrides):
    from datetime import datetime, timezone

    now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
    defaults = {
        "sign_id": "sign_abc123_xxx",
        "stage": "signed",
        "created_at": now,
        "signed_at": now,
        "consent_given_at": now,
        "consent_terms_version": "v1.0",
        "hash_original": "a" * 64,
        "hash_signed": "b" * 64,
        "service_caller": "processes",
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _wire(
    h,
    monkeypatch,
    *,
    verify_result=None,
    row_by_serial=None,
    row_by_sign_id=None,
    signed_pdf_bytes: bytes = b"%PDF-1.7\nfake\n%%EOF",
    signed_pdf_size: int | None = None,
    s3_raises: Exception | None = None,
    requests_response=None,
    requests_raises: Exception | None = None,
):
    from libs.orm.signatures import Signatures

    monkeypatch.setattr(
        Signatures,
        "get_by_cert_serial",
        MagicMock(return_value=row_by_serial),
    )
    monkeypatch.setattr(
        Signatures,
        "get_by_sign_id",
        MagicMock(return_value=row_by_sign_id),
    )
    monkeypatch.setattr(
        h,
        "verify_pades_pdf",
        MagicMock(return_value=verify_result or _STOCK_VERIFY_RESULT),
    )

    # S3 stub (only used by the sign_id path).
    s3 = MagicMock()
    if s3_raises is not None:
        s3.get_object = MagicMock(side_effect=s3_raises)
    else:
        s3.get_object = MagicMock(
            return_value={
                "ContentLength": signed_pdf_size
                if signed_pdf_size is not None
                else len(signed_pdf_bytes),
                "Body": MagicMock(read=MagicMock(return_value=signed_pdf_bytes)),
            }
        )
    monkeypatch.setattr(h.boto3, "client", MagicMock(return_value=s3))

    # requests stub (only used by the URL path).
    fake_requests = MagicMock()
    if requests_raises is not None:
        fake_requests.get = MagicMock(side_effect=requests_raises)
    else:
        resp = requests_response or MagicMock()
        if requests_response is None:
            resp.raise_for_status = MagicMock()
            resp.iter_content = MagicMock(return_value=iter([signed_pdf_bytes]))
        fake_requests.get = MagicMock(return_value=resp)
    fake_requests.RequestException = h.requests.RequestException
    monkeypatch.setattr(h, "requests", fake_requests)


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------
class TestBody:
    def test_both_provided_rejected(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch)
        resp = h.handler(
            _event({"pdf_source_url": "https://x", "sign_id": "abc"}), None
        )
        assert resp["statusCode"] == 400
        assert "provide_one_of" in json.loads(resp["body"])["error"]

    def test_neither_provided_rejected(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch)
        resp = h.handler(_event({}), None)
        assert resp["statusCode"] == 400

    def test_non_https_url_rejected(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch)
        resp = h.handler(_event({"pdf_source_url": "ftp://nope"}), None)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["error"] == "invalid_pdf_source_url"


# ---------------------------------------------------------------------------
# URL mode
# ---------------------------------------------------------------------------
class TestUrlMode:
    def test_happy_path_returns_masked_signer(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch)
        resp = h.handler(_event({"pdf_source_url": "https://x/y.pdf"}), None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["valid"] is True
        assert body["signer"]["email_masked"] == "si***@example.com"
        # Full email is never returned in the "signer" section.
        assert "email" not in body["signer"]

    def test_url_download_failure_returns_400(self, load_handler, monkeypatch):
        import requests

        h = load_handler(__file__)
        _wire(h, monkeypatch, requests_raises=requests.ConnectionError("nope"))
        resp = h.handler(_event({"pdf_source_url": "https://x/y.pdf"}), None)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["error"] == "could_not_download_source_pdf"

    def test_url_payload_over_cap_returns_413(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        big_chunk = b"P" * (2 * 1024 * 1024)  # 2 MiB per iter step
        # 20 chunks * 2 MiB = 40 MiB > 25 MiB cap.
        resp_obj = MagicMock()
        resp_obj.raise_for_status = MagicMock()
        resp_obj.iter_content = MagicMock(
            return_value=iter([big_chunk] * 20)
        )
        _wire(h, monkeypatch, requests_response=resp_obj)
        resp = h.handler(_event({"pdf_source_url": "https://x/y.pdf"}), None)
        assert resp["statusCode"] == 413

    def test_enriches_with_ceremony_when_cert_serial_matches(
        self, load_handler, monkeypatch
    ):
        h = load_handler(__file__)
        row = _make_row(sign_id="sign_abc123_xxx")
        _wire(h, monkeypatch, row_by_serial=row)
        resp = h.handler(_event({"pdf_source_url": "https://x/y.pdf"}), None)
        body = json.loads(resp["body"])
        assert body["ceremony"] is not None
        assert body["ceremony"]["sign_id_short"] == "sign_a"  # 6 chars only
        assert body["ceremony"]["consent"]["terms_version"] == "v1.0"

    def test_no_ceremony_when_serial_unknown(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row_by_serial=None)
        resp = h.handler(_event({"pdf_source_url": "https://x/y.pdf"}), None)
        body = json.loads(resp["body"])
        assert body["ceremony"] is None


# ---------------------------------------------------------------------------
# sign_id mode
# ---------------------------------------------------------------------------
class TestSignIdMode:
    def test_unknown_sign_id_returns_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row_by_sign_id=None)
        resp = h.handler(_event({"sign_id": "nope"}), None)
        assert resp["statusCode"] == 404
        assert json.loads(resp["body"])["error"] == "unknown_sign_id"

    def test_row_not_signed_returns_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _make_row(stage="otp")
        _wire(h, monkeypatch, row_by_sign_id=row)
        resp = h.handler(_event({"sign_id": "abc"}), None)
        assert resp["statusCode"] == 404
        assert json.loads(resp["body"])["error"] == "ceremony_not_signed"

    def test_signed_row_returns_ceremony_context_without_extra_lookup(
        self, load_handler, monkeypatch
    ):
        """When the caller passes sign_id, we already have the row, so
        we must NOT hit `get_by_cert_serial` again (redundant DB round
        trip on a hot path)."""
        from libs.orm.signatures import Signatures

        h = load_handler(__file__)
        row = _make_row(sign_id="sign_abc123_xxx")
        _wire(h, monkeypatch, row_by_sign_id=row)
        resp = h.handler(_event({"sign_id": "sign_abc123_xxx"}), None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["ceremony"]["sign_id_short"] == "sign_a"
        Signatures.get_by_cert_serial.assert_not_called()

    def test_s3_fetch_failure_returns_500(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _make_row()
        _wire(
            h,
            monkeypatch,
            row_by_sign_id=row,
            s3_raises=RuntimeError("s3 down"),
        )
        resp = h.handler(_event({"sign_id": "sign_abc123_xxx"}), None)
        assert resp["statusCode"] == 500
        assert json.loads(resp["body"])["error"] == "could_not_read_signed_pdf"

    def test_signed_pdf_too_large_returns_413(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _make_row()
        _wire(
            h,
            monkeypatch,
            row_by_sign_id=row,
            signed_pdf_size=100 * 1024 * 1024,  # 100 MiB, over 25 MiB cap
        )
        resp = h.handler(_event({"sign_id": "sign_abc123_xxx"}), None)
        assert resp["statusCode"] == 413


# ---------------------------------------------------------------------------
# Failure paths from verify_pades_pdf itself
# ---------------------------------------------------------------------------
class TestVerificationFailures:
    def test_tampered_document_forwards_reason(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(
            h,
            monkeypatch,
            verify_result={
                "valid": False,
                "document_integrity": False,
                "signature_valid": True,
                "certificate_valid": True,
                "signer_email": "signer@example.com",
                "signer_name": "Signer",
                "cert_serial": "c" * 32,
                "signed_at": "2026-09-21T00:00:00+00:00",
                "reason": "document_tampered",
            },
        )
        resp = h.handler(_event({"pdf_source_url": "https://x/y.pdf"}), None)
        body = json.loads(resp["body"])
        assert body["valid"] is False
        assert body["document_integrity"] is False
        assert body["reason"] == "document_tampered"

    def test_untrusted_root_reported(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(
            h,
            monkeypatch,
            verify_result={
                "valid": False,
                "document_integrity": True,
                "signature_valid": True,
                "certificate_valid": False,
                "signer_email": None,
                "signer_name": None,
                "cert_serial": None,
                "signed_at": None,
                "reason": "certificate_untrusted",
            },
        )
        resp = h.handler(_event({"pdf_source_url": "https://x/y.pdf"}), None)
        body = json.loads(resp["body"])
        assert body["certificate_valid"] is False
        # No cert_serial -> no ceremony lookup, no context.
        assert body["ceremony"] is None
        assert body["signer"]["email_masked"] is None
