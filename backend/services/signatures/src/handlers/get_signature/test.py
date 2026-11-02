"""Unit tests for the signatures/get_signature Lambda."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4


_SIGN_LOCATION = [{"page": 1, "x_pct": 9.0, "y_pct": 87.5, "width_pct": 28.0}]


def _row(created_at, **overrides):
    defaults = dict(
        id=str(uuid4()),
        stage="FORM",
        doc_s3_key="0192f4a8-7b3c-7abc-8def-1234567890ab.pdf",
        sign_location=_SIGN_LOCATION,
        created_at=created_at,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def _event(signature_id) -> dict:
    return {"queryStringParameters": {"signature_id": str(signature_id)}}


def test_get_signature_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(created_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "presign_download", MagicMock(return_value="https://signed-url"))

    resp = h.handler(_event(row.id), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["id"] == row.id
    assert body["stage"] == "FORM"
    assert body["sign_location"] == _SIGN_LOCATION
    assert body["doc_url"] == "https://signed-url"
    assert "expires_at" in body
    # no private fields such as the raw doc_s3_key are exposed
    assert "doc_s3_key" not in body


def test_get_signature_missing_signature_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler({"queryStringParameters": {}}, None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "signature_id is required"}


def test_get_signature_invalid_signature_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event("not-a-uuid"), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid signature_id"}


def test_get_signature_not_found_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=None)))

    resp = h.handler(_event(uuid4()), None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "signature_not_found"}


def test_get_signature_past_signing_window_returns_410(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(created_at=datetime.now(timezone.utc) - timedelta(minutes=21))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "presign_download", MagicMock(side_effect=AssertionError))

    resp = h.handler(_event(row.id), None)

    assert resp["statusCode"] == 410
    assert json.loads(resp["body"]) == {"error": "signature_expired"}


def test_get_signature_right_at_window_edge_still_succeeds(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _row(created_at=datetime.now(timezone.utc) - timedelta(minutes=14, seconds=59))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "presign_download", MagicMock(return_value="https://signed-url"))

    resp = h.handler(_event(row.id), None)

    assert resp["statusCode"] == 200
