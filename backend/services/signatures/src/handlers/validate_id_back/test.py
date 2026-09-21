"""Unit tests for signatures/validate_id_back."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from libs.core.responses import HandledError


def _event(sign_id: str) -> dict:
    return {"pathParameters": {"sign_id": sign_id}, "body": None}


def _fake_row(**overrides) -> MagicMock:
    defaults = {
        "sign_id": "sign_abc",
        "stage": "identity",  # normally called after id_front already validated
        "signer_email": "s@example.com",
        "signer_name": "S",
        "signature_location": {"page": 1, "x_pct": 20, "y_pct": 30},
        "expires_at": datetime(2026, 12, 31, tzinfo=timezone.utc),
        "created_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _wire(h, monkeypatch, *, row, detected_lines, key="the-key", size=1234):
    from libs.orm.signatures import Signatures

    monkeypatch.setattr(
        Signatures, "get_by_sign_id", MagicMock(return_value=row)
    )
    monkeypatch.setattr(h, "resolve_evidence_key", MagicMock(return_value=key))
    monkeypatch.setattr(h, "evidence_size", MagicMock(return_value=size))
    monkeypatch.setattr(h, "detect_text", MagicMock(return_value=detected_lines))
    return row


def _lines(*, count: int, confidence: float = 95.0) -> list[dict]:
    return [
        {"DetectedText": f"BACK LINE {i}", "Confidence": confidence, "Type": "LINE"}
        for i in range(count)
    ]


# ---------------------------------------------------------------------------
# Auth / stage
# ---------------------------------------------------------------------------
class TestPreconditions:
    def test_unknown_sign_id_returns_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=None, detected_lines=[])
        assert h.handler(_event("nope"), None)["statusCode"] == 404

    def test_terminal_stage_returns_410(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(
            h,
            monkeypatch,
            row=_fake_row(stage="failed"),
            detected_lines=_lines(count=3),
        )
        assert h.handler(_event("sign_abc"), None)["statusCode"] == 410

    def test_stage_signing_returns_409(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(
            h,
            monkeypatch,
            row=_fake_row(stage="signing"),
            detected_lines=_lines(count=3),
        )
        assert h.handler(_event("sign_abc"), None)["statusCode"] == 409


# ---------------------------------------------------------------------------
# Evidence resolution
# ---------------------------------------------------------------------------
class TestEvidenceResolution:
    def test_missing_evidence_returns_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row()
        _wire(h, monkeypatch, row=row, detected_lines=[])
        monkeypatch.setattr(
            h,
            "resolve_evidence_key",
            MagicMock(side_effect=HandledError("evidence_missing", 404)),
        )
        assert h.handler(_event("sign_abc"), None)["statusCode"] == 404

    def test_too_large_returns_413(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(), detected_lines=[])
        monkeypatch.setattr(
            h,
            "evidence_size",
            MagicMock(side_effect=HandledError("evidence_too_large", 413)),
        )
        assert h.handler(_event("sign_abc"), None)["statusCode"] == 413


# ---------------------------------------------------------------------------
# Heuristics -- back side needs at least 2 confident LINE detections
# ---------------------------------------------------------------------------
class TestHeuristics:
    def test_one_line_rejected(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row()
        _wire(h, monkeypatch, row=row, detected_lines=_lines(count=1))
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 422
        assert (
            json.loads(resp["body"])["error"]
            == "id_back_invalid_too_few_legible_lines"
        )
        row.attach_evidence.assert_not_called()

    def test_low_confidence_lines_do_not_count(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(
            h,
            monkeypatch,
            row=_fake_row(),
            detected_lines=_lines(count=3, confidence=40.0),
        )
        assert h.handler(_event("sign_abc"), None)["statusCode"] == 422


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
class TestHappyPath:
    def test_two_confident_lines_pass(self, load_handler, monkeypatch):
        """The back side is sparse; two confident LINE detections are
        enough. Deliberately looser than the front, no digit-run check."""
        h = load_handler(__file__)
        row = _fake_row()
        _wire(
            h,
            monkeypatch,
            row=row,
            detected_lines=_lines(count=2),
            key="transactions/sign_abc/id/back.png",
        )
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 200
        row.attach_evidence.assert_called_once_with(
            "id_back", "transactions/sign_abc/id/back.png"
        )
        row.mark_evidence_validated.assert_called_once_with("id_back")

    def test_text_free_response(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(
            h,
            monkeypatch,
            row=_fake_row(),
            detected_lines=_lines(count=4),
        )
        body = json.loads(h.handler(_event("sign_abc"), None)["body"])
        assert body.get("detected_lines") == 4
        assert "text" not in body and "lines" not in body
