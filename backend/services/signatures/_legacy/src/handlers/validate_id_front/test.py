"""Unit tests for signatures/validate_id_front."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from libs.core.responses import HandledError


def _event(sign_id: str) -> dict:
    # No body: the handler re-derives the S3 key from evidence_type.
    return {"pathParameters": {"sign_id": sign_id}, "body": None}


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


def _wire(h, monkeypatch, *, row, detected_lines, key="the-key", size=1234):
    """Stubs Signatures + the three helpers the handler pulls from
    utils.evidence. Returns the row so tests can inspect .mock_calls."""
    from libs.orm.signatures import Signatures

    monkeypatch.setattr(
        Signatures, "get_by_sign_id", MagicMock(return_value=row)
    )
    monkeypatch.setattr(h, "resolve_evidence_key", MagicMock(return_value=key))
    monkeypatch.setattr(h, "evidence_size", MagicMock(return_value=size))
    monkeypatch.setattr(h, "detect_text", MagicMock(return_value=detected_lines))
    return row


def _lines(*, count: int, with_id_digits: bool, confidence: float = 95.0) -> list[dict]:
    """Builds a plausible Rekognition `DetectText` response payload."""
    lines = [
        {"DetectedText": f"HEADER LINE {i}", "Confidence": confidence, "Type": "LINE"}
        for i in range(count - 1)
    ]
    if with_id_digits:
        lines.append(
            {"DetectedText": "1.234.567.890", "Confidence": confidence, "Type": "LINE"}
        )
    else:
        lines.append(
            {"DetectedText": "NO DIGITS HERE", "Confidence": confidence, "Type": "LINE"}
        )
    return lines


# ---------------------------------------------------------------------------
# Auth / stage
# ---------------------------------------------------------------------------
class TestPreconditions:
    def test_unknown_sign_id_returns_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=None, detected_lines=[])
        resp = h.handler(_event("nope"), None)
        assert resp["statusCode"] == 404

    def test_terminal_stage_signed_returns_410(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(
            h,
            monkeypatch,
            row=_fake_row(stage="signed"),
            detected_lines=_lines(count=4, with_id_digits=True),
        )
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 410
        assert json.loads(resp["body"]) == {"error": "ceremony_signed"}

    def test_terminal_stage_expired_returns_410(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(
            h,
            monkeypatch,
            row=_fake_row(stage="expired"),
            detected_lines=_lines(count=4, with_id_digits=True),
        )
        assert h.handler(_event("sign_abc"), None)["statusCode"] == 410

    def test_stage_otp_returns_409(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(
            h,
            monkeypatch,
            row=_fake_row(stage="otp"),
            detected_lines=_lines(count=4, with_id_digits=True),
        )
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 409


# ---------------------------------------------------------------------------
# Evidence resolution
# ---------------------------------------------------------------------------
class TestEvidenceResolution:
    def test_missing_evidence_returns_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row()
        _wire(h, monkeypatch, row=row, detected_lines=[])
        # resolve_evidence_key raises the same 404 path as the real helper.
        monkeypatch.setattr(
            h,
            "resolve_evidence_key",
            MagicMock(side_effect=HandledError("evidence_missing", 404)),
        )
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 404
        assert json.loads(resp["body"]) == {"error": "evidence_missing"}

    def test_too_large_returns_413(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row()
        _wire(h, monkeypatch, row=row, detected_lines=[])
        monkeypatch.setattr(
            h,
            "evidence_size",
            MagicMock(side_effect=HandledError("evidence_too_large", 413)),
        )
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 413


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------
class TestHeuristics:
    def test_too_few_lines_is_rejected(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row()
        _wire(
            h,
            monkeypatch,
            row=row,
            detected_lines=_lines(count=2, with_id_digits=True),
        )
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 422
        assert json.loads(resp["body"])["error"] == "id_front_invalid_too_few_legible_lines"
        row.attach_evidence.assert_not_called()
        row.mark_evidence_validated.assert_not_called()

    def test_low_confidence_lines_do_not_count(self, load_handler, monkeypatch):
        """3 lines but all below the 70% confidence threshold -> rejected."""
        h = load_handler(__file__)
        row = _fake_row()
        _wire(
            h,
            monkeypatch,
            row=row,
            detected_lines=_lines(count=4, with_id_digits=True, confidence=50.0),
        )
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 422
        assert (
            json.loads(resp["body"])["error"]
            == "id_front_invalid_too_few_legible_lines"
        )

    def test_no_id_number_is_rejected(self, load_handler, monkeypatch):
        """Enough legible lines but zero digit runs -> rejected."""
        h = load_handler(__file__)
        row = _fake_row()
        _wire(
            h,
            monkeypatch,
            row=row,
            detected_lines=_lines(count=4, with_id_digits=False),
        )
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 422
        assert (
            json.loads(resp["body"])["error"]
            == "id_front_invalid_no_id_number_detected"
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
class TestHappyPath:
    def test_happy_path_attaches_and_marks_validated(
        self, load_handler, monkeypatch
    ):
        h = load_handler(__file__)
        row = _fake_row()
        _wire(
            h,
            monkeypatch,
            row=row,
            detected_lines=_lines(count=4, with_id_digits=True),
            key="transactions/sign_abc/id/front.jpg",
        )
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 200
        payload = json.loads(resp["body"])
        assert payload["sign_id"] == "sign_abc"
        assert payload["detected_lines"] == 4
        # attach_evidence recorded the key, mark_evidence_validated stamped
        # it -- in that order (attach clears validated_at, so the reverse
        # would strand the ceremony).
        row.attach_evidence.assert_called_once_with(
            "id_front", "transactions/sign_abc/id/front.jpg"
        )
        row.mark_evidence_validated.assert_called_once_with("id_front")

    def test_digit_run_across_spaces_is_accepted(self, load_handler, monkeypatch):
        """OCR often splits a 10-digit ID like '1 234 567 890' across lines
        but keeps consecutive digits within a single line. We only require
        SIX consecutive digits within any single line."""
        h = load_handler(__file__)
        row = _fake_row()
        lines = [
            {"DetectedText": "NAME", "Confidence": 99.0, "Type": "LINE"},
            {"DetectedText": "SURNAME", "Confidence": 99.0, "Type": "LINE"},
            {"DetectedText": "0123456789", "Confidence": 99.0, "Type": "LINE"},
        ]
        _wire(h, monkeypatch, row=row, detected_lines=lines)
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 200

    def test_response_does_not_leak_raw_ocr(self, load_handler, monkeypatch):
        """The response returns a count, not the actual text lines --
        those may contain PII (name, address, etc.)."""
        h = load_handler(__file__)
        row = _fake_row()
        _wire(
            h,
            monkeypatch,
            row=row,
            detected_lines=_lines(count=5, with_id_digits=True),
        )
        resp = h.handler(_event("sign_abc"), None)
        body = json.loads(resp["body"])
        assert "detected_lines" in body
        assert isinstance(body["detected_lines"], int)
        assert "text" not in body and "lines" not in body
