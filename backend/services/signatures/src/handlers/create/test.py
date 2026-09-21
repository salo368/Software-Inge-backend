"""Unit tests for signatures/create.

The handler uses:
  * `X-Service-Key` M2M auth loaded from SSM (mocked here).
  * `requests.get` to download the source PDF (mocked).
  * `boto3.client("s3").put_object` for the transactions/... key (fake
    boto3 accepts anything by default).
  * `Signatures.create` to persist the row (mocked to skip the DB).
  * `_frontend_url` -> SSM (mocked to a fixed string).

All AWS/network/DB interactions are stubbed; the tests exercise validation,
happy-path wiring, and the error branches.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


_VALID_BODY = {
    "pdf_source_url": "https://source.example.com/doc.pdf",
    "signature_location": {"page": 1, "x_pct": 20, "y_pct": 30},
    "signer_email": "signer@example.com",
    "signer_name": "Test Signer",
    "callback_url": "https://caller.example.com/webhook/signatures",
    "service_caller": "processes",
}
_SERVICE_KEY = "sk-super-secret-abc123"


def _fake_pdf(size: int = 512) -> bytes:
    """Any bytes that pass the `%PDF-` prefix + min-length check."""
    return b"%PDF-1.4\n" + (b"x" * size)


def _build_event(headers: dict, body: dict | None) -> dict:
    return {
        "headers": headers,
        "body": json.dumps(body) if body is not None else None,
    }


def _wire_common(h, monkeypatch, *, service_key_value: str = _SERVICE_KEY):
    """Sets up the mocks every happy-path test needs."""
    import utils.auth as auth_mod

    monkeypatch.setattr(auth_mod, "_load_service_key", lambda: service_key_value)
    auth_mod._reset_service_key_cache_for_tests()

    monkeypatch.setattr(h, "_frontend_url", lambda: "https://app.test")
    h._reset_frontend_url_cache_for_tests()

    fake_resp = MagicMock()
    fake_resp.content = _fake_pdf()
    fake_resp.raise_for_status = MagicMock()
    monkeypatch.setattr(h.requests, "get", MagicMock(return_value=fake_resp))

    fake_row = MagicMock(
        sign_id="sign_xyz_abc",
        expires_at=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(h.Signatures, "create", MagicMock(return_value=fake_row))
    monkeypatch.setattr(h, "new_sign_id", lambda: "sign_xyz_abc")

    fake_s3 = MagicMock()
    monkeypatch.setattr(h.boto3, "client", MagicMock(return_value=fake_s3))
    return {"s3": fake_s3, "row": fake_row}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class TestServiceKeyAuth:
    def test_missing_header_returns_401(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire_common(h, monkeypatch)
        resp = h.handler(_build_event({}, _VALID_BODY), None)
        assert resp["statusCode"] == 401
        assert json.loads(resp["body"]) == {"error": "missing_service_key"}

    def test_wrong_key_returns_401(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire_common(h, monkeypatch)
        resp = h.handler(
            _build_event({"x-service-key": "wrong-key"}, _VALID_BODY), None
        )
        assert resp["statusCode"] == 401
        assert json.loads(resp["body"]) == {"error": "invalid_service_key"}

    def test_ssm_misconfigured_returns_500(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire_common(h, monkeypatch)
        import utils.auth as auth_mod

        def _boom():
            raise RuntimeError("SSM_SIGNATURES_SERVICE_KEY env var is not set")

        monkeypatch.setattr(auth_mod, "_load_service_key", _boom)
        auth_mod._reset_service_key_cache_for_tests()

        resp = h.handler(
            _build_event({"x-service-key": _SERVICE_KEY}, _VALID_BODY), None
        )
        assert resp["statusCode"] == 500
        assert json.loads(resp["body"]) == {"error": "internal_server_error"}


# ---------------------------------------------------------------------------
# Body validation (401 already passed at this point)
# ---------------------------------------------------------------------------
class TestBodyValidation:
    def _call(self, load_handler, monkeypatch, body):
        h = load_handler(__file__)
        _wire_common(h, monkeypatch)
        return h.handler(_build_event({"x-service-key": _SERVICE_KEY}, body), None)

    def test_missing_pdf_source_url(self, load_handler, monkeypatch):
        body = dict(_VALID_BODY)
        body.pop("pdf_source_url")
        resp = self._call(load_handler, monkeypatch, body)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "invalid_pdf_source_url"}

    def test_non_https_pdf_source_url(self, load_handler, monkeypatch):
        body = dict(_VALID_BODY, pdf_source_url="http://source.example.com/doc.pdf")
        resp = self._call(load_handler, monkeypatch, body)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "invalid_pdf_source_url"}

    def test_bad_signature_location_page(self, load_handler, monkeypatch):
        body = dict(_VALID_BODY)
        body["signature_location"] = {"page": 0, "x_pct": 10, "y_pct": 10}
        resp = self._call(load_handler, monkeypatch, body)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "invalid_signature_location"}

    def test_bad_signature_location_pct_out_of_range(
        self, load_handler, monkeypatch
    ):
        body = dict(_VALID_BODY)
        body["signature_location"] = {"page": 1, "x_pct": 150, "y_pct": 10}
        resp = self._call(load_handler, monkeypatch, body)
        assert resp["statusCode"] == 400

    def test_bad_signer_email(self, load_handler, monkeypatch):
        body = dict(_VALID_BODY, signer_email="not-an-email")
        resp = self._call(load_handler, monkeypatch, body)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "invalid_signer_email"}

    def test_http_callback_url_rejected(self, load_handler, monkeypatch):
        body = dict(_VALID_BODY, callback_url="http://caller.example.com/webhook")
        resp = self._call(load_handler, monkeypatch, body)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "invalid_callback_url"}

    def test_callback_url_none_is_allowed(self, load_handler, monkeypatch):
        body = dict(_VALID_BODY)
        body.pop("callback_url")
        resp = self._call(load_handler, monkeypatch, body)
        assert resp["statusCode"] == 201


# ---------------------------------------------------------------------------
# Source PDF download / shape
# ---------------------------------------------------------------------------
class TestSourceDownload:
    def test_download_failure_returns_400(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire_common(h, monkeypatch)
        import requests as req

        def _boom(*a, **kw):
            raise req.RequestException("connection reset")

        monkeypatch.setattr(h.requests, "get", _boom)
        resp = h.handler(
            _build_event({"x-service-key": _SERVICE_KEY}, _VALID_BODY), None
        )
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "could_not_download_source_pdf"}

    def test_non_pdf_bytes_rejected(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire_common(h, monkeypatch)
        bad = MagicMock()
        bad.content = b"<html>not a pdf</html>"
        bad.raise_for_status = MagicMock()
        monkeypatch.setattr(h.requests, "get", MagicMock(return_value=bad))
        resp = h.handler(
            _build_event({"x-service-key": _SERVICE_KEY}, _VALID_BODY), None
        )
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "source_is_not_a_pdf"}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
class TestHappyPath:
    def test_returns_201_with_expected_payload(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        mocks = _wire_common(h, monkeypatch)

        resp = h.handler(
            _build_event({"x-service-key": _SERVICE_KEY}, _VALID_BODY), None
        )

        assert resp["statusCode"] == 201
        payload = json.loads(resp["body"])
        assert payload["sign_id"] == "sign_xyz_abc"
        assert payload["sign_url"] == "https://app.test/sign/sign_xyz_abc"
        assert isinstance(payload["hash_original"], str)
        assert len(payload["hash_original"]) == 64  # SHA-256 hex length

    def test_uploads_pdf_to_signatures_bucket_before_db_write(
        self, load_handler, monkeypatch
    ):
        """Order matters: if S3 fails there must be no orphan DB row."""
        h = load_handler(__file__)
        mocks = _wire_common(h, monkeypatch)

        order: list[str] = []
        mocks["s3"].put_object.side_effect = lambda **kw: order.append("s3")
        h.Signatures.create.side_effect = lambda **kw: (
            order.append("db") or mocks["row"]
        )

        h.handler(_build_event({"x-service-key": _SERVICE_KEY}, _VALID_BODY), None)
        assert order == ["s3", "db"]

    def test_s3_failure_returns_500_and_no_db_write(
        self, load_handler, monkeypatch
    ):
        h = load_handler(__file__)
        mocks = _wire_common(h, monkeypatch)
        mocks["s3"].put_object.side_effect = RuntimeError("s3 kaput")
        h.Signatures.create.reset_mock()

        resp = h.handler(
            _build_event({"x-service-key": _SERVICE_KEY}, _VALID_BODY), None
        )
        assert resp["statusCode"] == 500
        assert json.loads(resp["body"]) == {"error": "could_not_persist_source_pdf"}
        h.Signatures.create.assert_not_called()

    def test_hash_is_sha256_of_source_bytes(self, load_handler, monkeypatch):
        import hashlib

        h = load_handler(__file__)
        _wire_common(h, monkeypatch)
        pdf = _fake_pdf(size=1024)
        fake_resp = MagicMock(content=pdf, raise_for_status=MagicMock())
        monkeypatch.setattr(h.requests, "get", MagicMock(return_value=fake_resp))

        resp = h.handler(
            _build_event({"x-service-key": _SERVICE_KEY}, _VALID_BODY), None
        )
        payload = json.loads(resp["body"])
        assert payload["hash_original"] == hashlib.sha256(pdf).hexdigest()

    def test_missing_frontend_url_returns_500(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire_common(h, monkeypatch)
        monkeypatch.setattr(h, "_frontend_url", lambda: "")

        resp = h.handler(
            _build_event({"x-service-key": _SERVICE_KEY}, _VALID_BODY), None
        )
        assert resp["statusCode"] == 500
        assert json.loads(resp["body"]) == {"error": "frontend_url_not_configured"}
