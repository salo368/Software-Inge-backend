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
        raw_signed_s3_key=None,
        signed_s3_key=None,
        doc_hash=None,
        signed_hash=None,
        signed_at=None,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def _signed_row(created_at, stage="SIGNED"):
    return _row(
        created_at=created_at,
        stage=stage,
        raw_signed_s3_key="signatures/x/raw_signed.pdf",
        signed_s3_key="signatures/x/signed.pdf",
        doc_hash="a" * 64,
        signed_hash="b" * 64,
        signed_at=created_at + timedelta(minutes=4),
    )


def _presign_by_key(bucket, key):
    return f"https://presigned/{key}"


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
    # nothing signed yet
    assert body["raw_signed_url"] is None
    assert body["signed_url"] is None
    assert body["doc_hash"] is None
    assert body["signed_hash"] is None
    assert body["signed_at"] is None


def test_get_signature_signed_exposes_both_files_and_hashes(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = _signed_row(created_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "presign_download", MagicMock(side_effect=_presign_by_key))

    resp = h.handler(_event(row.id), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["stage"] == "SIGNED"
    assert body["raw_signed_url"] == "https://presigned/signatures/x/raw_signed.pdf"
    assert body["signed_url"] == "https://presigned/signatures/x/signed.pdf"
    assert body["doc_hash"] == "a" * 64
    assert body["signed_hash"] == "b" * 64
    assert body["signed_at"] == str(row.signed_at)
    # only presigned URLs go out, never the raw S3 keys
    assert "signed_s3_key" not in body
    assert "raw_signed_s3_key" not in body


def test_get_signature_finished_or_signing_rows_ignore_window(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "presign_download", MagicMock(side_effect=_presign_by_key))

    old = datetime.now(timezone.utc) - timedelta(hours=3)
    for stage in ("SIGNING", "SIGNED", "FAILED"):
        row = _signed_row(created_at=old, stage=stage)
        monkeypatch.setattr(h, "Signatures", MagicMock(get_by_id=MagicMock(return_value=row)))

        resp = h.handler(_event(row.id), None)

        assert resp["statusCode"] == 200, stage
        assert json.loads(resp["body"])["stage"] == stage


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
