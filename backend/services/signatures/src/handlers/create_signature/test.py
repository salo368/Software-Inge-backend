"""Unit tests for the signatures/create_signature Lambda."""
from __future__ import annotations

import base64
import json
import re
import time
from unittest.mock import MagicMock
from uuid import UUID


_PDF_BYTES = b"%PDF-1.4\n%% unit test\n%%EOF\n"

_SIGN_LOCATION = [{"page": 1, "x_pct": 9.0, "y_pct": 87.5, "width_pct": 28.0}]
_SIGNATORY = "Juan Perez"

_UUID7_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.pdf$"
)


def _event(body: bytes, *, base64_encoded: bool, sign_location=_SIGN_LOCATION,
           signatory=_SIGNATORY) -> dict:
    query_params = {}
    if sign_location is not None:
        query_params["sign_location"] = json.dumps(sign_location)
    if signatory is not None:
        query_params["signatory"] = signatory

    event = {"queryStringParameters": query_params}
    if base64_encoded:
        event.update(body=base64.b64encode(body).decode(), isBase64Encoded=True)
    else:
        event.update(body=body.decode("latin-1"), isBase64Encoded=False)
    return event


def test_create_signature_happy_path_base64(load_handler, monkeypatch):
    h = load_handler(__file__)

    upload_mock = MagicMock()
    monkeypatch.setattr(h, "upload_from_bytes", upload_mock)

    created = MagicMock(
        id="row-1", stage="FORM", doc_s3_key=None,
        signatory=_SIGNATORY, sign_location=_SIGN_LOCATION,
    )
    create_mock = MagicMock(return_value=created)
    monkeypatch.setattr(h, "Signatures", MagicMock(create=create_mock))

    resp = h.handler(_event(_PDF_BYTES, base64_encoded=True), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {
        "id": "row-1", "stage": "FORM", "doc_s3_key": None,
        "signatory": _SIGNATORY, "sign_location": _SIGN_LOCATION,
    }

    bucket, key, data = upload_mock.call_args.args
    assert data == _PDF_BYTES
    assert _UUID7_RE.match(key)
    assert upload_mock.call_args.kwargs["content_type"] == "application/pdf"

    create_mock.assert_called_once_with(key, _SIGN_LOCATION, _SIGNATORY)


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


def test_create_signature_multi_page_sign_location(load_handler, monkeypatch):
    h = load_handler(__file__)

    monkeypatch.setattr(h, "upload_from_bytes", MagicMock())
    create_mock = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(h, "Signatures", MagicMock(create=create_mock))

    multi_page = [
        {"page": 1, "x_pct": 9.0, "y_pct": 87.5, "width_pct": 28.0},
        {"page": 2, "x_pct": 9.0, "y_pct": 87.5, "width_pct": 28.0},
    ]
    h.handler(_event(_PDF_BYTES, base64_encoded=True, sign_location=multi_page), None)

    assert create_mock.call_args.args[1] == multi_page


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

    resp = h.handler(_event(b"", base64_encoded=False), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "a file is required"}


def test_create_signature_missing_sign_location_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Signatures", MagicMock(create=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(_PDF_BYTES, base64_encoded=True, sign_location=None), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "sign_location is required"}


def test_create_signature_invalid_json_sign_location_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Signatures", MagicMock(create=MagicMock(side_effect=AssertionError)))

    event = _event(_PDF_BYTES, base64_encoded=True)
    event["queryStringParameters"]["sign_location"] = "{not-json"

    resp = h.handler(event, None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "sign_location must be valid JSON"}


def test_create_signature_empty_list_sign_location_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Signatures", MagicMock(create=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(_PDF_BYTES, base64_encoded=True, sign_location=[]), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "sign_location must be a non-empty list"}


def test_create_signature_non_list_sign_location_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Signatures", MagicMock(create=MagicMock(side_effect=AssertionError)))

    event = _event(_PDF_BYTES, base64_encoded=True)
    event["queryStringParameters"]["sign_location"] = json.dumps({"page": 1})

    resp = h.handler(event, None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "sign_location must be a non-empty list"}


def test_create_signature_missing_signatory_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Signatures", MagicMock(create=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(_PDF_BYTES, base64_encoded=True, signatory=None), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "signatory is required"}


def test_create_signature_blank_signatory_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "upload_from_bytes", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Signatures", MagicMock(create=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_event(_PDF_BYTES, base64_encoded=True, signatory="   "), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "signatory is required"}
