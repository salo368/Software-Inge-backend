"""Unit tests for the signatures/validate Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock


def _event(token: str, body: dict) -> dict:
    return {"pathParameters": {"token": token}, "body": json.dumps(body)}


def test_validate_face_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = MagicMock(stage="pending", face_key="signatures/xyz/face.jpg", attach_evidence=MagicMock())
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_token=MagicMock(return_value=row)))
    # Bypass Rekognition entirely: report a positive face detection.
    monkeypatch.setattr(h, "_has_face", MagicMock(return_value=True))

    resp = h.handler(_event("xyz", {"type": "face"}), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["valid"] is True
    # A valid photo must NOT be detached.
    row.attach_evidence.assert_not_called()


def test_validate_invalid_type_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(
        h,
        "Signatures",
        MagicMock(get_by_token=MagicMock(return_value=MagicMock(stage="pending"))),
    )

    resp = h.handler(_event("xyz", {"type": "not_a_type"}), None)

    assert resp["statusCode"] == 400
    assert "type must be one of" in json.loads(resp["body"])["error"]


def test_validate_rejects_and_detaches_evidence(load_handler, monkeypatch):
    """A photo that fails Rekognition must be detached so the ceremony rolls
    back to whatever stage the remaining evidence supports."""
    h = load_handler(__file__)

    row = MagicMock(
        stage="pending",
        cedula_front_key="signatures/xyz/cedula_front.jpg",
        attach_evidence=MagicMock(),
    )
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_token=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "_detected_lines", MagicMock(return_value=["totally unrelated text"]))

    resp = h.handler(_event("xyz", {"type": "cedula_front"}), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["valid"] is False
    row.attach_evidence.assert_called_once_with("cedula_front", None)
