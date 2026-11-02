"""Unit tests for signatures/register_signature."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from libs.core.responses import HandledError


# 8-byte PNG magic header. Real PNGs continue with an IHDR chunk, but
# the handler only checks the first 8 bytes.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff\xe0"


def _event(sign_id: str) -> dict:
    return {"pathParameters": {"sign_id": sign_id}, "body": None}


def _fake_row(**overrides) -> MagicMock:
    defaults = {
        "sign_id": "sign_abc",
        "stage": "identity",
        "signer_email": "s@example.com",
        "signer_name": "S",
        "signature_location": {"page": 1, "x_pct": 20, "y_pct": 30},
        "expires_at": datetime(2026, 12, 31, tzinfo=timezone.utc),
        "created_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _wire(
    h,
    monkeypatch,
    *,
    row,
    data: bytes,
    size: int | None = None,
    key: str = "transactions/sign_abc/signature.png",
):
    from libs.orm.signatures import Signatures

    monkeypatch.setattr(
        Signatures, "get_by_sign_id", MagicMock(return_value=row)
    )
    monkeypatch.setattr(h, "resolve_evidence_key", MagicMock(return_value=key))
    monkeypatch.setattr(
        h, "evidence_size", MagicMock(return_value=size if size is not None else len(data))
    )
    monkeypatch.setattr(h, "get_evidence_bytes", MagicMock(return_value=data))
    return row


# ---------------------------------------------------------------------------
# Auth / stage
# ---------------------------------------------------------------------------
class TestPreconditions:
    def test_unknown_sign_id_returns_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=None, data=_PNG_MAGIC + b"x" * 2000)
        assert h.handler(_event("nope"), None)["statusCode"] == 404

    def test_terminal_stage_returns_410(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(
            h,
            monkeypatch,
            row=_fake_row(stage="signed"),
            data=_PNG_MAGIC + b"x" * 2000,
        )
        assert h.handler(_event("sign_abc"), None)["statusCode"] == 410

    def test_stage_otp_returns_409(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(
            h,
            monkeypatch,
            row=_fake_row(stage="otp"),
            data=_PNG_MAGIC + b"x" * 2000,
        )
        assert h.handler(_event("sign_abc"), None)["statusCode"] == 409


# ---------------------------------------------------------------------------
# Evidence resolution
# ---------------------------------------------------------------------------
class TestEvidenceResolution:
    def test_missing_evidence_returns_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(), data=_PNG_MAGIC + b"x" * 2000)
        monkeypatch.setattr(
            h,
            "resolve_evidence_key",
            MagicMock(side_effect=HandledError("evidence_missing", 404)),
        )
        assert h.handler(_event("sign_abc"), None)["statusCode"] == 404


# ---------------------------------------------------------------------------
# Format & size
# ---------------------------------------------------------------------------
class TestFormatAndSize:
    def test_empty_canvas_returns_422(self, load_handler, monkeypatch):
        """Under 1 KiB is treated as an empty canvas even if the magic
        bytes are technically correct."""
        h = load_handler(__file__)
        row = _fake_row()
        _wire(
            h,
            monkeypatch,
            row=row,
            data=_PNG_MAGIC + b"x" * 100,
            size=200,
        )
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 422
        assert json.loads(resp["body"])["error"] == "signature_invalid_empty"
        row.attach_evidence.assert_not_called()

    def test_wrong_magic_returns_422(self, load_handler, monkeypatch):
        """The client tried to sneak a JPEG through the PNG-only slot."""
        h = load_handler(__file__)
        row = _fake_row()
        _wire(
            h,
            monkeypatch,
            row=row,
            data=_JPEG_MAGIC + b"x" * 2000,
        )
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 422
        assert json.loads(resp["body"])["error"] == "signature_invalid_not_png"
        row.attach_evidence.assert_not_called()

    def test_too_large_returns_413(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(), data=b"")
        monkeypatch.setattr(
            h,
            "evidence_size",
            MagicMock(side_effect=HandledError("evidence_too_large", 413)),
        )
        assert h.handler(_event("sign_abc"), None)["statusCode"] == 413


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
class TestHappyPath:
    def test_valid_png_attaches_but_does_not_mark_validated(
        self, load_handler, monkeypatch
    ):
        """`signature` has no separate validation step (no biometric
        check), so only `attach_evidence` is called -- not
        `mark_evidence_validated`."""
        h = load_handler(__file__)
        row = _fake_row()
        _wire(
            h,
            monkeypatch,
            row=row,
            data=_PNG_MAGIC + b"x" * 20000,
        )
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 200
        payload = json.loads(resp["body"])
        assert payload["sign_id"] == "sign_abc"
        assert payload["bytes"] == 8 + 20000  # magic + payload
        row.attach_evidence.assert_called_once_with(
            "signature", "transactions/sign_abc/signature.png"
        )
        row.mark_evidence_validated.assert_not_called()
