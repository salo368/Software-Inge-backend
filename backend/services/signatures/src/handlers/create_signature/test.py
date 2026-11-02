"""Unit tests for the signatures/create_signature Lambda."""
from __future__ import annotations

import base64
import json
import re
import time
from unittest.mock import MagicMock
from uuid import UUID


_PDF_BYTES = b"%PDF-1.4\n%% unit test\n%%EOF\n"

_UUID7_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.pdf$"
)


def _event(body: bytes, *, base64_encoded: bool) -> dict:
    if base64_encoded:
        return {"body": base64.b64encode(body).decode(), "isBase64Encoded": True}
    return {"body": body.decode("latin-1"), "isBase64Encoded": False}


def test_create_signature_happy_path_base64(load_handler, monkeypatch):
    h = load_handler(__file__)

    upload_mock = MagicMock()
    monkeypatch.setattr(h, "upload_from_bytes", upload_mock)

    created = MagicMock(id="row-1", stage="FORM", doc_s3_key=None, sign_location=None)
    create_mock = MagicMock(return_value=created)
    monkeypatch.setattr(h, "Signatures", MagicMock(create=create_mock))

    resp = h.handler(_event(_PDF_BYTES, base64_encoded=True), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {
        "id": "row-1", "stage": "FORM", "doc_s3_key": None, "sign_location": None
    }

    bucket, key, data = upload_mock.call_args.args
    assert data == _PDF_BYTES
    assert _UUID7_RE.match(key)
    assert upload_mock.call_args.kwargs["content_type"] == "application/pdf"

    create_mock.assert_called_once_with(key)


def test_create_signature_happy_path_raw_body(load_handler, monkeypatch):
    h = load_handler(__file__)

    upload_mock = MagicMock()
    monkeypatch.setattr(h, "upload_from_bytes", upload_mock)
    monkeypatch.setattr(
        h, "Signatures", MagicMock(create=MagicMock(return_value=MagicMock()))
    )

    h.handler(_event(_PDF_BYTES, base64_encoded=False), None)

    bucket, key, data = upload_mock.call_args.args
    assert data == _PDF_BYTES


def test_create_signature_uuid7_keys_are_time_ordered(load_handler, monkeypatch):
    h = load_handler(__file__)

    keys = []
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock(side_effect=lambda b, k, d, **kw: keys.append(k)))
    monkeypatch.setattr(h, "Signatures", MagicMock(create=MagicMock(return_value=MagicMock())))

    for _ in range(5):
        h.handler(_event(_PDF_BYTES, base64_encoded=True), None)
        time.sleep(0.002)  # UUIDv7 only orders across distinct milliseconds.

    assert keys == sorted(keys)
    for key in keys:
        assert _UUID7_RE.match(key)
        # version nibble must be 7 and variant bits must be 10xxxxxx.
        parsed = UUID(key[:-4])
        assert parsed.version == 7


def test_create_signature_missing_body_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Signatures", MagicMock(create=MagicMock(side_effect=AssertionError)))

    resp = h.handler({"body": None}, None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "a file is required"}
