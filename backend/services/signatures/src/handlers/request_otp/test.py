"""Unit tests for signatures/request_otp."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock


def _event(sign_id: str) -> dict:
    return {"pathParameters": {"sign_id": sign_id}, "body": None}


_OTP_EXPIRES = datetime(2026, 9, 21, 13, 0, tzinfo=timezone.utc)


def _fake_row(**overrides) -> MagicMock:
    defaults = {
        "sign_id": "sign_abc",
        "stage": "consent",
        "signer_email": "signer@example.com",
        "signer_name": "Signer",
        "signature_location": {"page": 1, "x_pct": 20, "y_pct": 30},
        "expires_at": datetime(2026, 12, 31, tzinfo=timezone.utc),
        "created_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
        "masked_email": "si***@example.com",
    }
    defaults.update(overrides)
    m = MagicMock(**defaults)
    m.otp_expires_at = _OTP_EXPIRES

    # Emulate issue_otp: returns plaintext + advances stage.
    def _issue_otp():
        m.otp_hash = "sha256hash"
        m.otp_expires_at = _OTP_EXPIRES
        m.stage = "otp"
        return "123456"

    m.issue_otp = MagicMock(side_effect=_issue_otp)
    m.public_dict = MagicMock(
        return_value={"otp": {"attempts_left": 5, "expires_at": None}}
    )
    return m


def _wire(h, monkeypatch, row, *, send_email_returns=True):
    from libs.orm.signatures import Signatures

    monkeypatch.setattr(
        Signatures, "get_by_sign_id", MagicMock(return_value=row)
    )
    send_mock = MagicMock(return_value=send_email_returns)
    monkeypatch.setattr(h, "send_email", send_mock)
    return row, send_mock


# ---------------------------------------------------------------------------
# Auth / stage
# ---------------------------------------------------------------------------
class TestPreconditions:
    def test_unknown_sign_id_returns_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=None)
        assert h.handler(_event("nope"), None)["statusCode"] == 404

    def test_terminal_stage_returns_410(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(stage="signed"))
        assert h.handler(_event("sign_abc"), None)["statusCode"] == 410

    def test_stage_identity_returns_409(self, load_handler, monkeypatch):
        """No consent yet -> no OTP."""
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(stage="identity"))
        assert h.handler(_event("sign_abc"), None)["statusCode"] == 409


# ---------------------------------------------------------------------------
# Issuance + email
# ---------------------------------------------------------------------------
class TestIssuance:
    def test_happy_path_issues_and_sends_email(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row, send_mock = _wire(h, monkeypatch, row=_fake_row())
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 200
        row.issue_otp.assert_called_once()
        send_mock.assert_called_once()
        # (to, subject, html) positional args
        to, subject, html = send_mock.call_args.args
        assert to == "signer@example.com"
        assert "verification code" in subject.lower()
        # The plaintext OTP must appear in the email body (that's the
        # whole point) but NEVER in the response.
        assert "123456" in html
        assert "123456" not in resp["body"]

    def test_response_shape(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row())
        payload = json.loads(h.handler(_event("sign_abc"), None)["body"])
        assert payload["sign_id"] == "sign_abc"
        assert payload["stage"] == "otp"
        assert payload["signer_email_masked"] == "si***@example.com"
        assert payload["otp"]["expires_at"] == _OTP_EXPIRES.isoformat()
        assert payload["otp"]["attempts_left"] == 5
        assert payload["otp"]["email_sent"] is True

    def test_resend_from_otp_stage_is_allowed(self, load_handler, monkeypatch):
        """Signer hits 'resend'; issue_otp regenerates the hash and
        resets the attempt counter."""
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(stage="otp"))
        assert h.handler(_event("sign_abc"), None)["statusCode"] == 200

    def test_email_failure_still_returns_200(self, load_handler, monkeypatch):
        """SMTP misconfiguration must not roll back the OTP that was
        already issued and stored -- otherwise a burnt OTP would waste
        a slot the signer never got to use. Response flags
        `email_sent=False` so the frontend can surface it."""
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(), send_email_returns=False)
        resp = h.handler(_event("sign_abc"), None)
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["otp"]["email_sent"] is False


# ---------------------------------------------------------------------------
# Secrecy
# ---------------------------------------------------------------------------
class TestSecrecy:
    def test_otp_never_leaks_into_response(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row())
        body = h.handler(_event("sign_abc"), None)["body"]
        payload = json.loads(body)
        assert "123456" not in body
        # Neither in a nested key.
        assert "otp_plaintext" not in payload
        assert "code" not in payload["otp"]
