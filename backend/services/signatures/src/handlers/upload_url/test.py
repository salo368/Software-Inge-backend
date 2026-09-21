"""Unit tests for signatures/upload_url."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _event(sign_id: str, body: dict | None) -> dict:
    return {
        "pathParameters": {"sign_id": sign_id},
        "body": json.dumps(body) if body is not None else None,
    }


def _fake_row(**overrides) -> MagicMock:
    defaults = {
        "sign_id": "sign_abc",
        "stage": "created",
        "signer_email": "s@example.com",
        "signer_name": "S",
        "signature_location": {"page": 1, "x_pct": 20, "y_pct": 30},
        "expires_at": datetime(2026, 12, 31, tzinfo=timezone.utc),
        "created_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _wire(h, monkeypatch, row):
    from libs.orm.signatures import Signatures

    monkeypatch.setattr(
        Signatures, "get_by_sign_id", MagicMock(return_value=row)
    )
    fake_s3 = MagicMock()
    fake_s3.generate_presigned_url = MagicMock(
        return_value="https://s3.presigned/put"
    )
    monkeypatch.setattr(h.boto3, "client", MagicMock(return_value=fake_s3))
    return fake_s3


# ---------------------------------------------------------------------------
# Auth / preconditions
# ---------------------------------------------------------------------------
class TestPreconditions:
    def test_unknown_sign_id_returns_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=None)
        resp = h.handler(_event("nope", {"evidence_type": "cedula_front"}), None)
        assert resp["statusCode"] == 404

    def test_terminal_stage_signed_returns_410(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(stage="signed"))
        resp = h.handler(_event("sign_abc", {"evidence_type": "face"}), None)
        assert resp["statusCode"] == 410
        assert json.loads(resp["body"]) == {"error": "ceremony_signed"}

    def test_terminal_stage_expired_returns_410(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(stage="expired"))
        resp = h.handler(_event("sign_abc", {"evidence_type": "face"}), None)
        assert resp["statusCode"] == 410

    def test_stage_not_in_allowed_returns_409(self, load_handler, monkeypatch):
        """`otp_pending` is between consent and OTP verification; you
        should NOT be reuploading evidences at that point."""
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(stage="otp_pending"))
        resp = h.handler(_event("sign_abc", {"evidence_type": "face"}), None)
        assert resp["statusCode"] == 409


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------
class TestBodyValidation:
    def test_missing_evidence_type_returns_400(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row())
        resp = h.handler(_event("sign_abc", {}), None)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "invalid_evidence_type"}

    def test_unknown_evidence_type_returns_400(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row())
        resp = h.handler(
            _event("sign_abc", {"evidence_type": "passport_front"}), None
        )
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "invalid_evidence_type"}

    def test_signature_drawing_only_accepts_png(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row())
        resp = h.handler(
            _event(
                "sign_abc",
                {"evidence_type": "signature_drawing", "content_type": "image/jpeg"},
            ),
            None,
        )
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "invalid_content_type"}

    def test_cedula_rejects_non_image(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row())
        resp = h.handler(
            _event(
                "sign_abc",
                {"evidence_type": "cedula_front", "content_type": "application/pdf"},
            ),
            None,
        )
        assert resp["statusCode"] == 400


# ---------------------------------------------------------------------------
# Happy path -- keys and URL
# ---------------------------------------------------------------------------
class TestHappyPath:
    def test_cedula_front_jpg_key(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        s3 = _wire(h, monkeypatch, row=_fake_row())
        resp = h.handler(
            _event(
                "sign_abc",
                {"evidence_type": "cedula_front", "content_type": "image/jpeg"},
            ),
            None,
        )
        assert resp["statusCode"] == 200
        payload = json.loads(resp["body"])
        assert payload["key"] == "transactions/sign_abc/cedula/front.jpg"
        assert payload["upload_url"] == "https://s3.presigned/put"
        assert payload["expires_in"] == 300

    def test_cedula_back_png_key(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row())
        resp = h.handler(
            _event(
                "sign_abc",
                {"evidence_type": "cedula_back", "content_type": "image/png"},
            ),
            None,
        )
        assert json.loads(resp["body"])["key"] == "transactions/sign_abc/cedula/back.png"

    def test_face_default_content_type_jpg(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row())
        resp = h.handler(
            _event("sign_abc", {"evidence_type": "face"}),  # no content_type
            None,
        )
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["key"] == "transactions/sign_abc/face.jpg"

    def test_signature_drawing_png_key(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row())
        resp = h.handler(
            _event(
                "sign_abc",
                {"evidence_type": "signature_drawing", "content_type": "image/png"},
            ),
            None,
        )
        assert (
            json.loads(resp["body"])["key"]
            == "transactions/sign_abc/signature.png"
        )

    def test_presign_uses_signatures_bucket_and_short_ttl(
        self, load_handler, monkeypatch
    ):
        h = load_handler(__file__)
        s3 = _wire(h, monkeypatch, row=_fake_row())
        h.handler(
            _event("sign_abc", {"evidence_type": "face"}), None
        )
        call = s3.generate_presigned_url.call_args
        assert call.args[0] == "put_object"
        params = call.kwargs["Params"]
        assert params["Bucket"] == h.SIGNATURES_BUCKET
        assert params["ContentType"] == "image/jpeg"
        assert call.kwargs["ExpiresIn"] <= 60 * 10
