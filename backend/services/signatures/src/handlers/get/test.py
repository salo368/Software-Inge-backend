"""Unit tests for the signatures/get Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock


def _event(token: str) -> dict:
    return {"pathParameters": {"token": token}}


def test_signatures_get_happy_path_unsigned(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = MagicMock(
        pdf_key="signatures/xyz/investment-order.pdf",
        signed_pdf_key=None,
        public_dict=MagicMock(return_value={"token": "xyz", "stage": "created"}),
    )
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_token=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "presign_download", MagicMock(return_value="https://s3.test/pdf"))

    resp = h.handler(_event("xyz"), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["token"] == "xyz"
    assert body["pdf_url"] == "https://s3.test/pdf"
    assert "signed_pdf_url" not in body


def test_signatures_get_returns_signed_pdf_url_when_signed(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = MagicMock(
        pdf_key="k1",
        signed_pdf_key="k2",
        public_dict=MagicMock(return_value={"token": "xyz", "stage": "signed"}),
    )
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_token=MagicMock(return_value=row)))
    # each presign_download call gets a different URL
    monkeypatch.setattr(
        h,
        "presign_download",
        MagicMock(side_effect=["https://s3.test/pdf", "https://s3.test/signed"]),
    )

    resp = h.handler(_event("xyz"), None)

    body = json.loads(resp["body"])
    assert body["pdf_url"] == "https://s3.test/pdf"
    assert body["signed_pdf_url"] == "https://s3.test/signed"


def test_signatures_get_unknown_token_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_token=MagicMock(return_value=None)))
    monkeypatch.setattr(h, "presign_download", MagicMock(side_effect=AssertionError))

    resp = h.handler(_event("nope"), None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "signature_not_found"}
