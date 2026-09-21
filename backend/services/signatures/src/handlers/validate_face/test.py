"""Unit tests for signatures/validate_face."""

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
        "stage": "identity",
        "signer_email": "s@example.com",
        "signer_name": "S",
        "signature_location": {"page": 1, "x_pct": 20, "y_pct": 30},
        "expires_at": datetime(2026, 12, 31, tzinfo=timezone.utc),
        "created_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _wire(h, monkeypatch, *, row, faces, key="the-key", size=1234):
    from libs.orm.signatures import Signatures

    monkeypatch.setattr(
        Signatures, "get_by_sign_id", MagicMock(return_value=row)
    )
    monkeypatch.setattr(h, "resolve_evidence_key", MagicMock(return_value=key))
    monkeypatch.setattr(h, "evidence_size", MagicMock(return_value=size))
    monkeypatch.setattr(h, "detect_faces", MagicMock(return_value=faces))
    return row


def _face(
    *,
    confidence: float = 99.5,
    eyes_open: bool = True,
    eyes_conf: float = 95.0,
) -> dict:
    """Shape mirrors Rekognition FaceDetails entries with Attributes=DEFAULT."""
    return {
        "Confidence": confidence,
        "EyesOpen": {"Value": eyes_open, "Confidence": eyes_conf},
        "BoundingBox": {"Width": 0.3, "Height": 0.4, "Left": 0.3, "Top": 0.2},
    }


# ---------------------------------------------------------------------------
# Auth / stage
# ---------------------------------------------------------------------------
class TestPreconditions:
    def test_unknown_sign_id_returns_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=None, faces=[])
        assert h.handler(_event("nope"), None)["statusCode"] == 404

    def test_terminal_stage_returns_410(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(
            h,
            monkeypatch,
            row=_fake_row(stage="signed"),
            faces=[_face()],
        )
        assert h.handler(_event("sign_abc"), None)["statusCode"] == 410

    def test_stage_otp_returns_409(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(stage="otp"), faces=[_face()])
        assert h.handler(_event("sign_abc"), None)["statusCode"] == 409


# ---------------------------------------------------------------------------
# Evidence resolution
# ---------------------------------------------------------------------------
class TestEvidenceResolution:
    def test_missing_evidence_returns_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(), faces=[])
        monkeypatch.setattr(
            h,
            "resolve_evidence_key",
            MagicMock(side_effect=HandledError("evidence_missing", 404)),
        )
        assert h.handler(_event("sign_abc"), None)["statusCode"] == 404

    def test_too_large_returns_413(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(), faces=[])
        monkeypatch.setattr(
            h,
            "evidence_size",
            MagicMock(side_effect=HandledError("evidence_too_large", 413)),
        )
        assert h.handler(_event("sign_abc"), None)["statusCode"] == 413


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------
class TestHeuristics:
    def test_no_face_returns_422(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row()
        _wire(h, monkeypatch, row=row, faces=[])
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 422
        assert json.loads(resp["body"])["error"] == "face_invalid_no_face_detected"
        row.attach_evidence.assert_not_called()

    def test_multiple_faces_returns_422(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(), faces=[_face(), _face()])
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 422
        assert json.loads(resp["body"])["error"] == "face_invalid_multiple_faces"

    def test_low_confidence_returns_422(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(), faces=[_face(confidence=50.0)])
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 422
        assert json.loads(resp["body"])["error"] == "face_invalid_low_confidence"

    def test_closed_eyes_returns_422(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(), faces=[_face(eyes_open=False)])
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 422
        assert json.loads(resp["body"])["error"] == "face_invalid_eyes_closed"

    def test_low_eye_confidence_returns_422(self, load_handler, monkeypatch):
        """Rekognition may return eyes_open=True but with low confidence
        (e.g. the eyes are cropped or blurred). Reject to force a retake."""
        h = load_handler(__file__)
        _wire(
            h, monkeypatch, row=_fake_row(), faces=[_face(eyes_conf=40.0)]
        )
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 422
        assert json.loads(resp["body"])["error"] == "face_invalid_eyes_closed"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
class TestHappyPath:
    def test_single_face_high_confidence_passes(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row()
        _wire(
            h,
            monkeypatch,
            row=row,
            faces=[_face()],
            key="transactions/sign_abc/face.jpg",
        )
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 200
        row.attach_evidence.assert_called_once_with(
            "face", "transactions/sign_abc/face.jpg"
        )
        row.mark_evidence_validated.assert_called_once_with("face")

    def test_response_shape_minimal(self, load_handler, monkeypatch):
        """The response only leaks sign_id + stage -- never bounding boxes
        or facial landmarks, both of which are biometric PII."""
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(), faces=[_face()])
        body = json.loads(h.handler(_event("sign_abc"), None)["body"])
        assert set(body.keys()) == {"sign_id", "stage"}
