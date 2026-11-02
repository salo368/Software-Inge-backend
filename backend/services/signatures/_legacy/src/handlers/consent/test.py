"""Unit tests for signatures/consent."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _event(sign_id: str, body: dict | None) -> dict:
    return {
        "pathParameters": {"sign_id": sign_id},
        "body": json.dumps(body) if body is not None else None,
    }


def _fake_row(**overrides) -> MagicMock:
    defaults = {
        "sign_id": "sign_abc",
        "stage": "identity",
        "signer_email": "s@example.com",
        "signer_name": "S",
        "signature_location": {"page": 1, "x_pct": 20, "y_pct": 30},
        "consent_given_at": None,
        "consent_terms_version": None,
        "expires_at": datetime(2026, 12, 31, tzinfo=timezone.utc),
        "created_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    m = MagicMock(**defaults)

    # Emulate `give_consent`: stamps timestamp + version and moves stage.
    def _give_consent(terms_version):
        m.consent_given_at = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
        m.consent_terms_version = terms_version
        m.stage = "consent"

    m.give_consent = MagicMock(side_effect=_give_consent)
    return m


def _wire(h, monkeypatch, row):
    from libs.orm.signatures import Signatures

    monkeypatch.setattr(
        Signatures, "get_by_sign_id", MagicMock(return_value=row)
    )
    return row


# ---------------------------------------------------------------------------
# Auth / stage
# ---------------------------------------------------------------------------
class TestPreconditions:
    def test_unknown_sign_id_returns_404(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=None)
        assert h.handler(_event("nope", {"terms_version": "v1.0"}), None)[
            "statusCode"
        ] == 404

    def test_terminal_stage_signed_returns_410(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(stage="signed"))
        resp = h.handler(_event("sign_abc", {"terms_version": "v1.0"}), None)
        assert resp["statusCode"] == 410

    def test_stage_created_returns_409(self, load_handler, monkeypatch):
        """Signer hasn't uploaded anything -- can't consent yet."""
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(stage="created"))
        assert h.handler(_event("sign_abc", {"terms_version": "v1.0"}), None)[
            "statusCode"
        ] == 409

    def test_stage_otp_returns_409(self, load_handler, monkeypatch):
        """Consent already given, moved to OTP -- can't 're-consent'."""
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row(stage="otp"))
        assert h.handler(_event("sign_abc", {"terms_version": "v1.0"}), None)[
            "statusCode"
        ] == 409


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------
class TestBodyValidation:
    def test_missing_terms_version_returns_400(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row())
        resp = h.handler(_event("sign_abc", {}), None)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["error"] == "missing_terms_version"

    def test_empty_terms_version_returns_400(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row())
        resp = h.handler(_event("sign_abc", {"terms_version": ""}), None)
        assert resp["statusCode"] == 400

    def test_unknown_terms_version_returns_400(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch, row=_fake_row())
        resp = h.handler(
            _event("sign_abc", {"terms_version": "v99.99"}), None
        )
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["error"] == "unknown_terms_version"


# ---------------------------------------------------------------------------
# ORM interaction
# ---------------------------------------------------------------------------
class TestOrmInteraction:
    def test_happy_path_calls_give_consent(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        row = _wire(h, monkeypatch, row=_fake_row())
        resp = h.handler(
            _event("sign_abc", {"terms_version": "v1.0"}), None
        )
        assert resp["statusCode"] == 200
        row.give_consent.assert_called_once_with("v1.0")
        payload = json.loads(resp["body"])
        assert payload["sign_id"] == "sign_abc"
        assert payload["stage"] == "consent"
        assert payload["consent"]["terms_version"] == "v1.0"

    def test_evidence_not_complete_returns_409(self, load_handler, monkeypatch):
        """ORM's `give_consent` raises ValueError when
        `all_evidences_ready` is False; handler maps that to 409."""
        h = load_handler(__file__)
        row = _fake_row()
        row.give_consent = MagicMock(side_effect=ValueError("not ready"))
        _wire(h, monkeypatch, row=row)
        resp = h.handler(
            _event("sign_abc", {"terms_version": "v1.0"}), None
        )
        assert resp["statusCode"] == 409
        assert json.loads(resp["body"])["error"] == "evidence_not_complete"

    def test_idempotent_reconfirm_same_version(self, load_handler, monkeypatch):
        """Signer clicks the button twice with the same version -> 200
        without re-calling give_consent."""
        h = load_handler(__file__)
        already = _fake_row(
            stage="consent",
            consent_given_at=datetime(2026, 9, 21, 10, tzinfo=timezone.utc),
            consent_terms_version="v1.0",
        )
        _wire(h, monkeypatch, row=already)
        resp = h.handler(
            _event("sign_abc", {"terms_version": "v1.0"}), None
        )
        assert resp["statusCode"] == 200
        already.give_consent.assert_not_called()

    def test_idempotent_reconfirm_different_version_returns_409(
        self, load_handler, monkeypatch
    ):
        """Consenting again with a different terms_version would leave
        two audit records; reject it."""
        h = load_handler(__file__)
        already = _fake_row(
            stage="consent",
            consent_given_at=datetime(2026, 9, 21, 10, tzinfo=timezone.utc),
            consent_terms_version="v1.0",
        )
        _wire(h, monkeypatch, row=already)
        # Add a v2.0 to the accepted list for this test -- otherwise the
        # 'unknown_terms_version' check fires first.
        monkeypatch.setattr(
            h, "_KNOWN_TERMS_VERSIONS", ("v1.0", "v2.0")
        )
        resp = h.handler(
            _event("sign_abc", {"terms_version": "v2.0"}), None
        )
        assert resp["statusCode"] == 409
        assert (
            json.loads(resp["body"])["error"] == "consent_terms_version_mismatch"
        )
