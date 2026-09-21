"""Unit tests for signatures/get.

The handler is guarded by `require_sign_id`, which uses
`Signatures.get_by_sign_id`. Tests mock that ORM method plus the S3
presigned URL generator.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _event(sign_id: str | None) -> dict:
    return {"pathParameters": {"sign_id": sign_id} if sign_id else {}}


def _fake_row(**overrides) -> MagicMock:
    """Signatures row shaped like the ORM emits it."""
    defaults = {
        "sign_id": "sign_abc",
        "stage": "created",
        "signer_email": "signer@example.com",
        "signer_name": "Test Signer",
        "signature_location": {"page": 1, "x_pct": 20, "y_pct": 30},
        "expires_at": datetime(2026, 12, 31, tzinfo=timezone.utc),
        "created_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _wire(h, monkeypatch, row=None):
    """Auth passes when Signatures.get_by_sign_id returns a row."""
    from libs.orm.signatures import Signatures

    monkeypatch.setattr(
        Signatures, "get_by_sign_id", MagicMock(return_value=row)
    )
    fake_s3 = MagicMock()
    fake_s3.generate_presigned_url = MagicMock(
        return_value="https://s3.presigned/original.pdf"
    )
    monkeypatch.setattr(h.boto3, "client", MagicMock(return_value=fake_s3))
    return fake_s3


class TestSignIdAuth:
    def test_missing_sign_id_path_returns_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=None)
        resp = h.handler({"pathParameters": None}, None)
        assert resp["statusCode"] == 404
        assert json.loads(resp["body"]) == {"error": "signature_not_found"}

    def test_empty_sign_id_returns_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=None)
        resp = h.handler(_event(""), None)
        assert resp["statusCode"] == 404
        assert json.loads(resp["body"]) == {"error": "signature_not_found"}

    def test_unknown_sign_id_returns_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=None)  # ORM returns None
        resp = h.handler(_event("nope"), None)
        assert resp["statusCode"] == 404
        assert json.loads(resp["body"]) == {"error": "signature_not_found"}


class TestHappyPath:
    def test_returns_full_state(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row()
        s3 = _wire(h, monkeypatch, row=row)

        resp = h.handler(_event("sign_abc"), None)

        assert resp["statusCode"] == 200
        payload = json.loads(resp["body"])
        assert payload["sign_id"] == "sign_abc"
        assert payload["stage"] == "created"
        assert payload["signer_email"] == "signer@example.com"
        assert payload["signer_name"] == "Test Signer"
        assert payload["signature_location"] == {
            "page": 1,
            "x_pct": 20,
            "y_pct": 30,
        }
        assert payload["pdf_url"] == "https://s3.presigned/original.pdf"
        assert payload["expires_at"].startswith("2026-12-31")
        assert payload["created_at"].startswith("2026-09-20")

    def test_pdf_url_points_to_correct_key(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row(sign_id="sign_xyz")
        s3 = _wire(h, monkeypatch, row=row)

        h.handler(_event("sign_xyz"), None)

        call = s3.generate_presigned_url.call_args
        assert call.args[0] == "get_object"
        params = call.kwargs["Params"]
        assert params["Bucket"] == h.SIGNATURES_BUCKET
        assert params["Key"] == "transactions/sign_xyz/original.pdf"
        # Short TTL so leaked URLs don't survive.
        assert call.kwargs["ExpiresIn"] <= 60 * 60

    def test_does_not_leak_sensitive_fields(self, load_handler, monkeypatch):
        """We don't want to expose callback_url, cert_serial, or hashes
        to whoever holds the sign_url (i.e. the signer)."""
        h = load_handler(__file__)
        row = _fake_row(
            callback_url="https://caller.example.com/webhook",
            cert_serial="serial-123",
            hash_original="abc" * 20,
        )
        _wire(h, monkeypatch, row=row)

        resp = h.handler(_event("sign_abc"), None)
        payload = json.loads(resp["body"])
        assert "callback_url" not in payload
        assert "cert_serial" not in payload
        assert "hash_original" not in payload
