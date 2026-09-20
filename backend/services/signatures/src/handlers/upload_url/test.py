"""Unit tests for the signatures/upload_url Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock


def _event(token: str, body: dict) -> dict:
    return {"pathParameters": {"token": token}, "body": json.dumps(body)}


def test_upload_url_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = MagicMock(stage="pending", attach_evidence=MagicMock())
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_token=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "presign_upload", MagicMock(return_value="https://s3.test/put"))

    resp = h.handler(_event("xyz", {"type": "signature", "content_type": "image/png"}), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["upload_url"] == "https://s3.test/put"
    assert body["key"] == "signatures/xyz/signature.png"
    assert body["upload_headers"] == {"Content-Type": "image/png"}
    row.attach_evidence.assert_called_once_with("signature", "signatures/xyz/signature.png")


def test_upload_url_invalid_type_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(
        h,
        "Signatures",
        MagicMock(get_by_token=MagicMock(return_value=MagicMock(stage="pending"))),
    )
    monkeypatch.setattr(h, "presign_upload", MagicMock(side_effect=AssertionError))

    resp = h.handler(_event("xyz", {"type": "not_a_type", "content_type": "image/png"}), None)

    assert resp["statusCode"] == 400
    assert "type must be one of" in json.loads(resp["body"])["error"]


def test_upload_url_already_signed_returns_409(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(
        h,
        "Signatures",
        MagicMock(get_by_token=MagicMock(return_value=MagicMock(stage="signed"))),
    )
    monkeypatch.setattr(h, "presign_upload", MagicMock(side_effect=AssertionError))

    resp = h.handler(_event("xyz", {"type": "signature", "content_type": "image/png"}), None)

    assert resp["statusCode"] == 409
    assert json.loads(resp["body"]) == {"error": "already_signed"}
