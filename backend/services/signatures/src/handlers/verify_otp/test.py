"""Unit tests for signatures/verify_otp."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from libs.utils.lambda_invoke import LambdaInvokeError


_NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
_FUTURE = _NOW + timedelta(minutes=5)
_PAST = _NOW - timedelta(minutes=5)


def _event(sign_id: str, body: dict | None) -> dict:
    return {
        "pathParameters": {"sign_id": sign_id},
        "body": json.dumps(body) if body is not None else None,
    }


def _fake_row(
    *,
    stage: str = "otp",
    otp_expires_at=_FUTURE,
    attempts_left: int = 5,
    otp_matches: bool = True,
) -> MagicMock:
    m = MagicMock(
        sign_id="sign_abc",
        stage=stage,
        signer_email="s@example.com",
        signer_name="S",
        signature_location={"page": 1, "x_pct": 20, "y_pct": 30},
        expires_at=datetime(2026, 12, 31, tzinfo=timezone.utc),
        created_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
    )
    m.otp_expires_at = otp_expires_at
    m.otp_matches = MagicMock(return_value=otp_matches)
    m.public_dict = MagicMock(
        return_value={"otp": {"attempts_left": attempts_left, "expires_at": None}}
    )

    # Emulate start_signing: advances stage.
    def _start_signing():
        m.stage = "signing"

    m.start_signing = MagicMock(side_effect=_start_signing)

    remaining = {"n": attempts_left}

    def _register_failed():
        remaining["n"] -= 1
        m.public_dict.return_value = {
            "otp": {"attempts_left": remaining["n"], "expires_at": None}
        }
        return remaining["n"]

    m.register_failed_attempt = MagicMock(side_effect=_register_failed)
    m.mark_failed = MagicMock()
    return m


def _wire(
    h,
    monkeypatch,
    row,
    *,
    sign_lambda_ready: bool = False,
    invoke_raises: Exception | None = None,
    now: datetime = _NOW,
):
    from libs.orm.signatures import Signatures

    monkeypatch.setattr(
        Signatures, "get_by_sign_id", MagicMock(return_value=row)
    )
    monkeypatch.setattr(h, "SIGN_LAMBDA_READY", sign_lambda_ready)
    monkeypatch.setattr(h, "_utcnow", lambda: now)
    invoke_mock = MagicMock(side_effect=invoke_raises)
    monkeypatch.setattr(h, "invoke_async", invoke_mock)
    monkeypatch.setattr(
        h, "resolve_function_name", lambda service, key: f"cdts-test-{service}-{key}"
    )
    return invoke_mock


# ---------------------------------------------------------------------------
# Auth / stage
# ---------------------------------------------------------------------------
class TestPreconditions:
    def test_unknown_sign_id_returns_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=None)
        assert h.handler(_event("nope", {"code": "123456"}), None)[
            "statusCode"
        ] == 404

    def test_terminal_stage_returns_410(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(stage="signed"))
        assert h.handler(_event("sign_abc", {"code": "123456"}), None)[
            "statusCode"
        ] == 410

    def test_stage_consent_returns_409(self, load_handler, monkeypatch):
        """No OTP issued yet -> cannot verify."""
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(stage="consent"))
        assert h.handler(_event("sign_abc", {"code": "123456"}), None)[
            "statusCode"
        ] == 409


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------
class TestBodyValidation:
    def test_missing_code_returns_400(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row())
        resp = h.handler(_event("sign_abc", {}), None)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["error"] == "missing_code"

    def test_non_string_code_returns_400(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row())
        resp = h.handler(_event("sign_abc", {"code": 123456}), None)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["error"] == "invalid_code_format"

    def test_bad_length_returns_400(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row())
        resp = h.handler(_event("sign_abc", {"code": "12345"}), None)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["error"] == "invalid_code_format"

    def test_non_digit_returns_400(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row())
        resp = h.handler(_event("sign_abc", {"code": "12345a"}), None)
        assert resp["statusCode"] == 400


# ---------------------------------------------------------------------------
# OTP expiry
# ---------------------------------------------------------------------------
class TestExpiry:
    def test_expired_returns_401(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row(otp_expires_at=_PAST)
        _wire(h, monkeypatch, row=row)
        resp = h.handler(_event("sign_abc", {"code": "123456"}), None)
        assert resp["statusCode"] == 401
        assert json.loads(resp["body"])["error"] == "otp_expired"
        row.start_signing.assert_not_called()

    def test_no_expires_at_returns_401(self, load_handler, monkeypatch):
        """Row is at stage='otp' but otp_expires_at is None (should not
        happen in normal flow, but a race between issue and verify
        could theoretically produce this). Treat as expired."""
        h = load_handler(__file__)
        row = _fake_row(otp_expires_at=None)
        _wire(h, monkeypatch, row=row)
        assert h.handler(_event("sign_abc", {"code": "123456"}), None)[
            "statusCode"
        ] == 401


# ---------------------------------------------------------------------------
# Wrong OTP -- attempts_left
# ---------------------------------------------------------------------------
class TestWrongOtp:
    def test_wrong_code_decrements_attempts(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row(attempts_left=5, otp_matches=False)
        _wire(h, monkeypatch, row=row)
        resp = h.handler(_event("sign_abc", {"code": "000000"}), None)
        assert resp["statusCode"] == 401
        body = json.loads(resp["body"])
        assert body["error"] == "otp_invalid"
        assert body["attempts_left"] == 4
        row.register_failed_attempt.assert_called_once()
        row.start_signing.assert_not_called()

    def test_last_attempt_locks_ceremony(self, load_handler, monkeypatch):
        """The 5th wrong attempt drives attempts_left to 0 -> mark
        the ceremony failed and return 429 so the microfront can show
        a terminal error state."""
        h = load_handler(__file__)
        row = _fake_row(attempts_left=1, otp_matches=False)
        _wire(h, monkeypatch, row=row)
        resp = h.handler(_event("sign_abc", {"code": "000000"}), None)
        assert resp["statusCode"] == 429
        assert json.loads(resp["body"])["error"] == "otp_max_attempts"
        row.mark_failed.assert_called_once_with("otp_max_attempts")

    def test_zero_attempts_before_verify_locks(self, load_handler, monkeypatch):
        """Defensive: if the row somehow arrived here with 0 attempts
        left, close the ceremony immediately."""
        h = load_handler(__file__)
        row = _fake_row(attempts_left=0)
        _wire(h, monkeypatch, row=row)
        resp = h.handler(_event("sign_abc", {"code": "123456"}), None)
        assert resp["statusCode"] == 429
        row.mark_failed.assert_called_once()


# ---------------------------------------------------------------------------
# Success path -- SIGN_LAMBDA_READY off (fase 4d)
# ---------------------------------------------------------------------------
class TestSuccessFlagOff:
    def test_correct_code_advances_but_skips_invoke(
        self, load_handler, monkeypatch
    ):
        h = load_handler(__file__)
        row = _fake_row(otp_matches=True)
        invoke_mock = _wire(h, monkeypatch, row=row, sign_lambda_ready=False)
        resp = h.handler(_event("sign_abc", {"code": "123456"}), None)
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["stage"] == "signing"
        row.start_signing.assert_called_once()
        invoke_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Success path -- SIGN_LAMBDA_READY on (fase 4e+)
# ---------------------------------------------------------------------------
class TestSuccessFlagOn:
    def test_correct_code_invokes_sign_lambda(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row(otp_matches=True)
        invoke_mock = _wire(h, monkeypatch, row=row, sign_lambda_ready=True)
        resp = h.handler(_event("sign_abc", {"code": "123456"}), None)
        assert resp["statusCode"] == 200
        invoke_mock.assert_called_once()
        # Function name resolved through resolve_function_name shim.
        fn, payload = invoke_mock.call_args.args
        assert fn == "cdts-test-signatures-sign"
        assert payload == {"sign_id": "sign_abc"}

    def test_invoke_failure_returns_502(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _fake_row(otp_matches=True)
        _wire(
            h,
            monkeypatch,
            row=row,
            sign_lambda_ready=True,
            invoke_raises=LambdaInvokeError(
                "cdts-test-signatures-sign",
                "boto_error",
                "ResourceNotFoundException",
            ),
        )
        resp = h.handler(_event("sign_abc", {"code": "123456"}), None)
        assert resp["statusCode"] == 502
        assert json.loads(resp["body"])["error"] == "sign_lambda_unavailable"
        # start_signing already fired before the failed invoke; the
        # ceremony is stuck at 'signing' for an operator to replay.
        row.start_signing.assert_called_once()
