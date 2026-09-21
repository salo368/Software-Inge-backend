"""Unit tests for processes/signature_callback.

The handler is a webhook receiver, so tests exercise `handler(event, ctx)`
with JSON bodies. All external dependencies are stubbed:

    * Processes.get_by_sign_id  -> MagicMock or None
    * Signatures.get_by_sign_id -> MagicMock or None

The tests focus on the DECISION TABLE (which stable `action` string
the handler returns for each ceremony stage) and on the AUTH MODEL
(payload is untrusted; we always re-read via Signatures ORM).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _event(body: dict | None = None, raw: str | None = None) -> dict:
    return {"body": raw if raw is not None else json.dumps(body or {})}


def _fake_process(**overrides):
    defaults = {
        "id": "proc-1",
        "signed_at": None,
        "mark_signed_at": MagicMock(),
    }
    defaults.update(overrides)
    m = MagicMock(**{k: v for k, v in defaults.items() if k != "mark_signed_at"})
    m.mark_signed_at = defaults["mark_signed_at"]

    # Implement idempotence on the stub the same way the ORM does, so
    # tests that check `already_marked` vs `signed_marked` behave.
    def _mark(signed_at):
        if m.signed_at is None:
            m.signed_at = signed_at

    m.mark_signed_at.side_effect = _mark
    return m


def _fake_ceremony(stage="signed", **overrides):
    defaults = {
        "sign_id": "sign_abc",
        "stage": stage,
        "signed_at": datetime(2026, 9, 21, 12, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _wire(h, monkeypatch, *, process=None, ceremony=None):
    monkeypatch.setattr(
        h.Processes, "get_by_sign_id", MagicMock(return_value=process)
    )
    monkeypatch.setattr(
        h.Signatures, "get_by_sign_id", MagicMock(return_value=ceremony)
    )


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------
class TestBody:
    def test_missing_sign_id_returns_400(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch)
        resp = h.handler(_event({}), None)
        assert resp["statusCode"] == 400
        assert json.loads(resp["body"])["error"] == "missing_sign_id"

    def test_empty_sign_id_returns_400(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch)
        resp = h.handler(_event({"sign_id": "   "}), None)
        assert resp["statusCode"] == 400

    def test_non_string_sign_id_returns_400(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        _wire(h, monkeypatch)
        resp = h.handler(_event({"sign_id": 123}), None)
        assert resp["statusCode"] == 400


# ---------------------------------------------------------------------------
# Routing (payload is untrusted; we always re-read from signatures)
# ---------------------------------------------------------------------------
class TestRouting:
    def test_unknown_sign_id_returns_process_not_found(
        self, load_handler, monkeypatch
    ):
        h = load_handler(__file__)
        _wire(h, monkeypatch, process=None)
        resp = h.handler(_event({"sign_id": "unknown"}), None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body == {"ok": True, "action": "process_not_found"}

    def test_process_bound_but_no_ceremony_row(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        proc = _fake_process()
        _wire(h, monkeypatch, process=proc, ceremony=None)
        resp = h.handler(_event({"sign_id": "sign_abc"}), None)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body == {"ok": True, "action": "signature_not_found"}
        proc.mark_signed_at.assert_not_called()

    def test_lookup_uses_sign_id_from_body(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        proc = _fake_process()
        ceremony = _fake_ceremony(stage="signed")
        _wire(h, monkeypatch, process=proc, ceremony=ceremony)
        h.handler(_event({"sign_id": "  sign_abc  "}), None)  # padded
        h.Processes.get_by_sign_id.assert_called_once_with("sign_abc")
        h.Signatures.get_by_sign_id.assert_called_once_with("sign_abc")

    def test_ignores_payload_stage_and_reads_authoritative(
        self, load_handler, monkeypatch
    ):
        """Zero-trust: an attacker could POST {stage: 'signed'} but if
        the ceremony in the DB is `otp`, we treat it as pending."""
        h = load_handler(__file__)
        proc = _fake_process()
        ceremony = _fake_ceremony(stage="otp")
        _wire(h, monkeypatch, process=proc, ceremony=ceremony)
        resp = h.handler(
            _event(
                {
                    "sign_id": "sign_abc",
                    # These fields are ALL noise; the handler must
                    # ignore them.
                    "stage": "signed",
                    "hash_signed": "b" * 64,
                    "signed_at": "2026-09-21T00:00:00+00:00",
                }
            ),
            None,
        )
        body = json.loads(resp["body"])
        assert body["action"] == "ceremony_pending"
        proc.mark_signed_at.assert_not_called()


# ---------------------------------------------------------------------------
# Ceremony stage -> action table
# ---------------------------------------------------------------------------
class TestStageDecisionTable:
    def test_signed_first_time_stamps_signed_at(
        self, load_handler, monkeypatch
    ):
        h = load_handler(__file__)
        proc = _fake_process(signed_at=None)
        ceremony = _fake_ceremony(
            stage="signed",
            signed_at=datetime(2026, 9, 21, 12, tzinfo=timezone.utc),
        )
        _wire(h, monkeypatch, process=proc, ceremony=ceremony)

        resp = h.handler(_event({"sign_id": "sign_abc"}), None)
        assert json.loads(resp["body"])["action"] == "signed_marked"
        proc.mark_signed_at.assert_called_once_with(ceremony.signed_at)
        assert proc.signed_at == ceremony.signed_at

    def test_signed_second_time_is_idempotent(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        previous = datetime(2026, 9, 21, 11, tzinfo=timezone.utc)
        proc = _fake_process(signed_at=previous)
        ceremony = _fake_ceremony(
            stage="signed",
            signed_at=datetime(2026, 9, 21, 12, tzinfo=timezone.utc),
        )
        _wire(h, monkeypatch, process=proc, ceremony=ceremony)

        resp = h.handler(_event({"sign_id": "sign_abc"}), None)
        assert json.loads(resp["body"])["action"] == "already_marked"
        # mark_signed_at is called but is a no-op on the ORM side; the
        # earlier timestamp is preserved.
        assert proc.signed_at == previous

    def test_failed_ceremony_returns_ceremony_failed(
        self, load_handler, monkeypatch
    ):
        h = load_handler(__file__)
        proc = _fake_process()
        ceremony = _fake_ceremony(stage="failed")
        _wire(h, monkeypatch, process=proc, ceremony=ceremony)
        resp = h.handler(_event({"sign_id": "sign_abc"}), None)
        assert json.loads(resp["body"])["action"] == "ceremony_failed"
        proc.mark_signed_at.assert_not_called()

    def test_expired_ceremony_returns_ceremony_failed(
        self, load_handler, monkeypatch
    ):
        h = load_handler(__file__)
        proc = _fake_process()
        ceremony = _fake_ceremony(stage="expired")
        _wire(h, monkeypatch, process=proc, ceremony=ceremony)
        resp = h.handler(_event({"sign_id": "sign_abc"}), None)
        assert json.loads(resp["body"])["action"] == "ceremony_failed"

    def test_mid_flow_stage_returns_pending(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        proc = _fake_process()
        for stage in ("created", "identity", "consent", "otp", "signing"):
            ceremony = _fake_ceremony(stage=stage)
            _wire(h, monkeypatch, process=proc, ceremony=ceremony)
            resp = h.handler(_event({"sign_id": "sign_abc"}), None)
            body = json.loads(resp["body"])
            assert (
                body["action"] == "ceremony_pending"
            ), f"stage={stage} produced action={body['action']}"
            proc.mark_signed_at.assert_not_called()


# ---------------------------------------------------------------------------
# Response contract
# ---------------------------------------------------------------------------
class TestResponseContract:
    def test_always_200_when_body_is_valid(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        # Even unknown sign_ids get 200 -- retries from a misdirected
        # webhook must not generate operator noise upstream.
        _wire(h, monkeypatch, process=None)
        resp = h.handler(_event({"sign_id": "nope"}), None)
        assert resp["statusCode"] == 200

    def test_response_shape(self, load_handler, monkeypatch):
        h = load_handler(__file__)
        proc = _fake_process()
        ceremony = _fake_ceremony(stage="signed")
        _wire(h, monkeypatch, process=proc, ceremony=ceremony)
        resp = h.handler(_event({"sign_id": "sign_abc"}), None)
        body = json.loads(resp["body"])
        assert set(body.keys()) == {"ok", "action"}
        assert body["ok"] is True
