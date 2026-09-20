"""Unit tests for the signatures/request_otp Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock


def _event(token: str) -> dict:
    return {"pathParameters": {"token": token}}


def test_request_otp_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = MagicMock(
        stage="pending",
        signature_key="signatures/xyz/signature.png",
        email="user@x.co",
        issue_otp=MagicMock(return_value="123456"),
    )
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_token=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "send_email", MagicMock(return_value=True))

    resp = h.handler(_event("xyz"), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body == {"status": "sent", "stage": "pending"}


def test_request_otp_already_signed_returns_409(load_handler, monkeypatch):
    h = load_handler(__file__)

    row = MagicMock(stage="signed", signature_key="x", issue_otp=MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_token=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "send_email", MagicMock(side_effect=AssertionError))

    resp = h.handler(_event("xyz"), None)

    assert resp["statusCode"] == 409
    assert json.loads(resp["body"]) == {"error": "already_signed"}


def test_request_otp_dev_stage_returns_otp_when_email_fails(load_handler, monkeypatch):
    """Outside production, a failed email must not block the flow: the OTP
    is echoed in the response so QA can finish the ceremony."""
    h = load_handler(__file__)
    monkeypatch.setattr(h, "STAGE", "dev")

    row = MagicMock(
        stage="pending",
        signature_key="x",
        email="user@x.co",
        issue_otp=MagicMock(return_value="654321"),
    )
    monkeypatch.setattr(h, "Signatures", MagicMock(get_by_token=MagicMock(return_value=row)))
    monkeypatch.setattr(h, "send_email", MagicMock(return_value=False))

    resp = h.handler(_event("xyz"), None)

    body = json.loads(resp["body"])
    assert body["status"] == "undelivered"
    assert body["dev_otp"] == "654321"
