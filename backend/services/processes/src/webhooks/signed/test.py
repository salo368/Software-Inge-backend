"""Unit tests for the processes/signed webhook Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4


def _process(stage="SIGNATURE"):
    return MagicMock(id=uuid4(), stage=stage)


def _event(signature_id, stage="SIGNED"):
    return {"body": json.dumps({"signature_id": str(signature_id), "stage": stage})}


def _patch(h, monkeypatch, process):
    processes = MagicMock(
        get_by_signature_id=MagicMock(return_value=process),
        advance_to_payment=MagicMock(),
    )
    monkeypatch.setattr(h, "Processes", processes)
    return processes


def test_signed_advances_process_to_payment(load_handler, monkeypatch):
    h = load_handler(__file__)
    process = _process("SIGNATURE")
    processes = _patch(h, monkeypatch, process)
    signature_id = uuid4()

    resp = h.handler(_event(signature_id), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"process_id": str(process.id), "advanced": True}
    processes.get_by_signature_id.assert_called_once_with(signature_id)
    processes.advance_to_payment.assert_called_once_with(process.id)


def test_signed_is_idempotent_when_process_already_advanced(load_handler, monkeypatch):
    h = load_handler(__file__)
    process = _process("PAYMENT")
    processes = _patch(h, monkeypatch, process)

    resp = h.handler(_event(uuid4()), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"process_id": str(process.id), "advanced": False}
    processes.advance_to_payment.assert_not_called()


def test_failed_signature_does_not_advance_process(load_handler, monkeypatch):
    h = load_handler(__file__)
    process = _process("SIGNATURE")
    processes = _patch(h, monkeypatch, process)

    resp = h.handler(_event(uuid4(), stage="FAILED"), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["advanced"] is False
    processes.advance_to_payment.assert_not_called()


def test_signed_unknown_signature_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    processes = _patch(h, monkeypatch, None)

    resp = h.handler(_event(uuid4()), None)

    assert resp["statusCode"] == 404
    processes.advance_to_payment.assert_not_called()


def test_signed_invalid_signature_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch(h, monkeypatch, _process())

    resp = h.handler({"body": json.dumps({"signature_id": "nope", "stage": "SIGNED"})}, None)

    assert resp["statusCode"] == 400


def test_signed_invalid_stage_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch(h, monkeypatch, _process())

    resp = h.handler(_event(uuid4(), stage="OTP"), None)

    assert resp["statusCode"] == 400


def test_signed_missing_body_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch(h, monkeypatch, _process())

    resp = h.handler({}, None)

    assert resp["statusCode"] == 400
