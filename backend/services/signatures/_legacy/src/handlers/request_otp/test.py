"""Unit tests for signatures/request_otp."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


def _event(sign_id: str, *, headers: dict | None = None) -> dict:
    return {
        "pathParameters": {"sign_id": sign_id},
        "body": None,
        "headers": headers or {},
    }


# 32-byte hex, matches the shape `bootstrap-signatures-v2.sh` writes.
_DEBUG_KEY_HEX = "b1a91cd6a2af41b8f1e7c14ea9dcb62a3ff9d2a1b0e5c81f0ad6217de3b48c05"


def _debug_hmac(sign_id: str, key: str = _DEBUG_KEY_HEX) -> str:
    return hmac.new(key.encode(), sign_id.encode(), hashlib.sha256).hexdigest()


@pytest.fixture(autouse=True)
def _reset_debug_key_cache(monkeypatch):
    """Every test starts with a cold debug-key cache so a prior test
    that enabled the feature doesn't leak into a test that shouldn't
    reach _load_debug_otp_key at all."""
    # Late import: handler module isn't loaded yet at collection time.
    yield


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


def _wire(
    h,
    monkeypatch,
    row,
    *,
    send_email_returns=True,
    debug_key: str | None = None,
):
    """Wires the handler for a request. `debug_key` controls the debug
    OTP escape hatch:
      * None  -> _load_debug_otp_key returns None (feature disabled).
      * str   -> _load_debug_otp_key returns the given key as bytes.
    Both modes reset the module-level cache so tests are independent.
    """
    from libs.orm.signatures import Signatures

    monkeypatch.setattr(
        Signatures, "get_by_sign_id", MagicMock(return_value=row)
    )
    send_mock = MagicMock(return_value=send_email_returns)
    monkeypatch.setattr(h, "send_email", send_mock)

    # Cold the cache and stub the loader.
    monkeypatch.setattr(h, "_debug_key", None, raising=False)
    monkeypatch.setattr(h, "_debug_key_loaded", False, raising=False)
    if debug_key is None:
        monkeypatch.setattr(h, "_load_debug_otp_key", lambda: None)
    else:
        key_bytes = debug_key.encode()
        monkeypatch.setattr(h, "_load_debug_otp_key", lambda: key_bytes)
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


# ---------------------------------------------------------------------------
# Debug OTP escape hatch (dev-only, integration tests)
# ---------------------------------------------------------------------------
class TestDebugOTP:
    """Verifies the HMAC-guarded plaintext disclosure path.

    Key invariants:
      * Response NEVER contains `_debug_otp` unless BOTH the debug key
        is provisioned AND the caller HMAC-signs sign_id correctly.
      * When the key is absent (production posture), even a maliciously
        provided header cannot leak the OTP.
      * HMAC is bound to sign_id, so a valid header for ceremony A does
        not authorize disclosure for ceremony B.
    """

    def test_no_debug_key_no_disclosure_even_with_header(
        self, load_handler, monkeypatch
    ):
        """Production posture: SSM param absent -> _load_debug_otp_key
        returns None -> feature disabled regardless of headers."""
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(), debug_key=None)
        headers = {"X-Debug-OTP-Signature": _debug_hmac("sign_abc")}
        payload = json.loads(
            h.handler(_event("sign_abc", headers=headers), None)["body"]
        )
        assert "_debug_otp" not in payload

    def test_debug_key_present_but_no_header_no_disclosure(
        self, load_handler, monkeypatch
    ):
        """Dev posture with key provisioned but caller didn't opt in.
        Every non-CI request goes through this path -- absolutely must
        NOT leak the OTP."""
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(), debug_key=_DEBUG_KEY_HEX)
        payload = json.loads(h.handler(_event("sign_abc"), None)["body"])
        assert "_debug_otp" not in payload

    def test_debug_key_present_wrong_hmac_no_disclosure(
        self, load_handler, monkeypatch
    ):
        """Caller sent a header but signed with the WRONG key. constant-
        time compare rejects."""
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(), debug_key=_DEBUG_KEY_HEX)
        headers = {
            "X-Debug-OTP-Signature": _debug_hmac(
                "sign_abc", key="00" * 32  # wrong key
            )
        }
        payload = json.loads(
            h.handler(_event("sign_abc", headers=headers), None)["body"]
        )
        assert "_debug_otp" not in payload

    def test_debug_key_valid_hmac_for_other_sign_id_no_disclosure(
        self, load_handler, monkeypatch
    ):
        """Replay resistance: HMAC is BOUND to sign_id. A header valid
        for ceremony X cannot leak the OTP of ceremony Y even though
        both ceremonies share the same debug key."""
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(sign_id="sign_abc"), debug_key=_DEBUG_KEY_HEX)
        headers = {
            "X-Debug-OTP-Signature": _debug_hmac("sign_xyz")  # different sign_id
        }
        payload = json.loads(
            h.handler(_event("sign_abc", headers=headers), None)["body"]
        )
        assert "_debug_otp" not in payload

    def test_debug_key_valid_hmac_discloses(self, load_handler, monkeypatch):
        """The happy path an integration test uses: correct key, correct
        binding, header present -> plaintext appears in the response."""
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(), debug_key=_DEBUG_KEY_HEX)
        headers = {"X-Debug-OTP-Signature": _debug_hmac("sign_abc")}
        resp = h.handler(_event("sign_abc", headers=headers), None)
        payload = json.loads(resp["body"])
        assert payload.get("_debug_otp") == "123456"
        # Public fields still there; disclosure is additive.
        assert payload["sign_id"] == "sign_abc"
        assert payload["stage"] == "otp"
        assert payload["otp"]["email_sent"] is True

    def test_header_is_case_insensitive(self, load_handler, monkeypatch):
        """API Gateway lowercases header names before invoking the
        Lambda. Match must be case-insensitive on our side."""
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(), debug_key=_DEBUG_KEY_HEX)
        headers = {"x-debug-otp-signature": _debug_hmac("sign_abc")}
        payload = json.loads(
            h.handler(_event("sign_abc", headers=headers), None)["body"]
        )
        assert payload.get("_debug_otp") == "123456"

    def test_disclosure_does_not_log_plaintext(
        self, load_handler, monkeypatch, caplog
    ):
        """Even a legitimate disclosure must not write the OTP into
        CloudWatch. Replay of the log stream should not reveal past
        OTPs."""
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(), debug_key=_DEBUG_KEY_HEX)
        headers = {"X-Debug-OTP-Signature": _debug_hmac("sign_abc")}
        with caplog.at_level("INFO"):
            h.handler(_event("sign_abc", headers=headers), None)
        joined_logs = "\n".join(r.getMessage() for r in caplog.records)
        assert "123456" not in joined_logs
