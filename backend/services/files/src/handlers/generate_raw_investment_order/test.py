"""Unit tests for the files/generate_raw_investment_order internal worker."""
from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4


def _bank_response(io_url="https://assets.test/order-forms/bancolombia.pdf", status_code=200):
    return {"statusCode": status_code, "body": json.dumps({"id": 1, "io_url": io_url})}


def _event(**overrides):
    body = dict(
        process_id=str(uuid4()),
        bank_id=1,
        submitted_form={"name": "Ana"},
        amount="1000000.00",
        term=180,
        rate="12.50",
    )
    body.update(overrides)
    return {"body": json.dumps({k: v for k, v in body.items() if v is not None})}


def _patch(h, monkeypatch, **overrides):
    mocks = dict(
        invoke_sync=MagicMock(return_value=_bank_response()),
        requests=MagicMock(),
        populate_investment_order=MagicMock(return_value=b"%PDF-1.4 populated"),
        upload_from_bytes=MagicMock(),
        presign_download=MagicMock(return_value="https://files.test/signed-get"),
    )
    mocks.update(overrides)
    mocks["requests"].get.return_value = MagicMock(content=b"%PDF-1.4 template", raise_for_status=MagicMock())
    for name, mock in mocks.items():
        monkeypatch.setattr(h, name, mock)
    return mocks


def test_happy_path_populates_and_uploads(load_handler, monkeypatch):
    h = load_handler(__file__)
    mocks = _patch(h, monkeypatch)
    process_id = str(uuid4())

    resp = h.handler(_event(process_id=process_id), None)

    assert resp["statusCode"] == 200
    result = json.loads(resp["body"])
    key = result["key"]
    assert result["process_id"] == process_id
    assert result["url"] == "https://files.test/signed-get"
    mocks["presign_download"].assert_called_once_with(h.BUCKET, key)
    assert result["sign_location"] == h.SIGNATURE_LOCATION
    assert key.startswith(f"processes/{process_id}/RAW_INVESTMENT_ORDER/") and key.endswith(".pdf")

    bank_call = mocks["invoke_sync"].call_args
    assert bank_call.args == ("get_bank", {"queryStringParameters": {"bank_id": "1"}})
    assert bank_call.kwargs["service"] == "banks"

    mocks["populate_investment_order"].assert_called_once_with(
        b"%PDF-1.4 template", form={"name": "Ana"}, amount="1000000.00", term=180, rate="12.50",
    )
    mocks["upload_from_bytes"].assert_called_once_with(
        h.BUCKET, key, b"%PDF-1.4 populated", "application/pdf",
        metadata={
            "process-id": process_id,
            "file-type": "RAW_INVESTMENT_ORDER",
            "original-name": "investment_order.pdf",
        },
    )


def test_missing_required_params(load_handler, monkeypatch):
    h = load_handler(__file__)
    mocks = _patch(h, monkeypatch)

    resp = h.handler(_event(submitted_form=None), None)

    assert resp["statusCode"] == 400
    mocks["upload_from_bytes"].assert_not_called()


def test_missing_commercial_terms(load_handler, monkeypatch):
    h = load_handler(__file__)
    mocks = _patch(h, monkeypatch)

    resp = h.handler(_event(rate=None), None)

    assert resp["statusCode"] == 400
    mocks["upload_from_bytes"].assert_not_called()


def test_bank_without_io_url(load_handler, monkeypatch):
    h = load_handler(__file__)
    mocks = _patch(h, monkeypatch, invoke_sync=MagicMock(return_value=_bank_response(io_url=None)))

    resp = h.handler(_event(), None)

    assert resp["statusCode"] == 422
    mocks["upload_from_bytes"].assert_not_called()


def test_get_bank_error_status(load_handler, monkeypatch):
    h = load_handler(__file__)
    mocks = _patch(h, monkeypatch, invoke_sync=MagicMock(return_value=_bank_response(status_code=404)))

    resp = h.handler(_event(bank_id=9), None)

    assert resp["statusCode"] == 502
    mocks["upload_from_bytes"].assert_not_called()
