"""Unit tests for signatures/get.

The handler is guarded by `require_sign_id`, which uses
`Signatures.get_by_sign_id`. Tests mock that ORM method plus the S3
presigned URL generator.

Response contract (v2):
  * Everything in `Signatures.public_dict()` (sign_id, stage,
    signer_email_masked, signature_location, uploads_state, consent,
    otp, hash_original, hash_signed, cert_serial, signed_at, created_at,
    expires_at).
  * Plus handler-only: `signer_name`, `pdf_url`, and conditionally
    `signed_pdf_url` (only when stage == 'signed').
  * NEVER: `callback_url`, `service_caller`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _event(sign_id: str | None) -> dict:
    return {"pathParameters": {"sign_id": sign_id} if sign_id else {}}


def _fake_row(**overrides) -> MagicMock:
    """Signatures row shaped like the ORM emits it.

    `public_dict` is set as a bound method-like MagicMock so callers can
    monkey with its return value per-test.
    """
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
    row = MagicMock(**defaults)
    # Default public_dict() shape. Tests can override per-case.
    row.public_dict = MagicMock(
        return_value={
            "sign_id": defaults["sign_id"],
            "stage": defaults["stage"],
            "signer_email_masked": "s******@example.com",
            "signature_location": defaults["signature_location"],
            # ORM key for the drawn signature is 'signature' (see
            # libs/orm/signatures.EVIDENCE_TYPES). The HTTP API accepts
            # 'signature_drawing' as the evidence_type in POST /upload-url;
            # the SPA has to translate.
            "uploads_state": {
                "id_front": {"uploaded": False, "validated": False},
                "id_back": {"uploaded": False, "validated": False},
                "face": {"uploaded": False, "validated": False},
                "signature": {"uploaded": False, "validated": None},
            },
            "consent": {"given": False, "given_at": None, "terms_version": None},
            "otp": {"requested": False, "expires_at": None, "attempts_left": 3},
            "hash_original": "abc" * 20,
            "hash_signed": None,
            "cert_serial": None,
            "signed_at": None,
            "created_at": defaults["created_at"].isoformat(),
            "expires_at": defaults["expires_at"].isoformat(),
        }
    )
    return row


def _wire(h, monkeypatch, row=None):
    """Auth passes when Signatures.get_by_sign_id returns a row."""
    from libs.orm.signatures import Signatures

    monkeypatch.setattr(
        Signatures, "get_by_sign_id", MagicMock(return_value=row)
    )
    fake_s3 = MagicMock()
    fake_s3.generate_presigned_url = MagicMock(
        side_effect=lambda op, Params, ExpiresIn: (
            f"https://s3.presigned/{Params['Key']}"
        )
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
    def test_returns_public_dict_plus_handler_extras(
        self, load_handler, monkeypatch
    ):
        h = load_handler(__file__)
        row = _fake_row()
        _wire(h, monkeypatch, row=row)

        resp = h.handler(_event("sign_abc"), None)

        assert resp["statusCode"] == 200
        payload = json.loads(resp["body"])
        # From public_dict()
        assert payload["sign_id"] == "sign_abc"
        assert payload["stage"] == "created"
        assert payload["signer_email_masked"] == "s******@example.com"
        assert payload["signature_location"] == {
            "page": 1,
            "x_pct": 20,
            "y_pct": 30,
        }
        assert "uploads_state" in payload
        assert "consent" in payload
        assert "otp" in payload
        assert payload["hash_original"] == "abc" * 20
        assert payload["expires_at"].startswith("2026-12-31")
        assert payload["created_at"].startswith("2026-09-20")
        # From handler
        assert payload["signer_name"] == "Test Signer"
        assert payload["pdf_url"].endswith("/original.pdf")

    def test_pdf_url_points_to_correct_key(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row(sign_id="sign_xyz")
        s3 = _wire(h, monkeypatch, row=row)

        h.handler(_event("sign_xyz"), None)

        # First call generates the original.pdf URL. Stage is 'created',
        # so the signed URL is NOT presigned (see next test).
        first_call = s3.generate_presigned_url.call_args_list[0]
        assert first_call.args[0] == "get_object"
        params = first_call.kwargs["Params"]
        assert params["Bucket"] == h.SIGNATURES_BUCKET
        assert params["Key"] == "transactions/sign_xyz/original.pdf"
        # Short TTL so leaked URLs don't survive a browsing session.
        assert first_call.kwargs["ExpiresIn"] <= 60 * 60

    def test_signed_pdf_url_absent_before_signed_stage(
        self, load_handler, monkeypatch
    ):
        """Any stage other than 'signed' MUST NOT include a
        `signed_pdf_url` -- the object doesn't exist yet."""
        h = load_handler(__file__)
        for stage in ("created", "identity", "consent", "otp", "signing"):
            row = _fake_row(stage=stage)
            row.public_dict = MagicMock(
                return_value={**row.public_dict.return_value, "stage": stage}
            )
            _wire(h, monkeypatch, row=row)

            resp = h.handler(_event("sign_abc"), None)
            payload = json.loads(resp["body"])
            assert "signed_pdf_url" not in payload, stage

    def test_signed_pdf_url_present_when_signed(
        self, load_handler, monkeypatch
    ):
        """Once stage == 'signed' the handler presigns and returns a URL
        pointing to `evidence-archive/{sign_id}/signed.pdf`."""
        h = load_handler(__file__)
        row = _fake_row(sign_id="sign_signed", stage="signed")
        row.public_dict = MagicMock(
            return_value={
                **row.public_dict.return_value,
                "stage": "signed",
                "sign_id": "sign_signed",
                "hash_signed": "def" * 20,
                "cert_serial": "SERIAL-1",
                "signed_at": "2026-09-21T12:34:56+00:00",
            }
        )
        s3 = _wire(h, monkeypatch, row=row)

        resp = h.handler(_event("sign_signed"), None)
        payload = json.loads(resp["body"])
        assert payload["stage"] == "signed"
        assert payload["signed_pdf_url"].endswith(
            "evidence-archive/sign_signed/signed.pdf"
        )
        # Two presigns: original + signed.
        assert s3.generate_presigned_url.call_count == 2
        keys = [
            call.kwargs["Params"]["Key"]
            for call in s3.generate_presigned_url.call_args_list
        ]
        assert "transactions/sign_signed/original.pdf" in keys
        assert "evidence-archive/sign_signed/signed.pdf" in keys

    def test_does_not_leak_internal_fields(self, load_handler, monkeypatch):
        """`callback_url` and `service_caller` are internal-only. The
        handler must never surface them, even if the ORM row carries
        them (they're stored on the row for the async callback worker).

        Note: `hash_original`, `hash_signed`, and `cert_serial` ARE
        exposed on purpose -- see handler docstring for why.
        """
        h = load_handler(__file__)
        row = _fake_row(
            callback_url="https://caller.example.com/webhook",
            service_caller="portal",
        )
        _wire(h, monkeypatch, row=row)

        resp = h.handler(_event("sign_abc"), None)
        payload = json.loads(resp["body"])
        assert "callback_url" not in payload
        assert "service_caller" not in payload
