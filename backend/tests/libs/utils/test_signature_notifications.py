"""Unit tests for `libs.utils.signature_notifications`."""
from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4

from libs.utils import signature_notifications as sn
from libs.utils.lambda_invoke import LambdaInvokeError


def _signed_call(sig_id, stage):
    return (
        ("signed", {"body": json.dumps({"signature_id": str(sig_id), "stage": stage})}),
        {"service": "processes"},
    )


def test_signed_invokes_processes_signed_and_notify_signed(monkeypatch):
    invoke_mock = MagicMock()
    monkeypatch.setattr(sn, "invoke_async", invoke_mock)

    sig_id = uuid4()
    sn.notify_terminal_state(sig_id, "SIGNED", notify_signer=True)

    args, kwargs = _signed_call(sig_id, "SIGNED")
    invoke_mock.assert_any_call(*args, **kwargs)
    invoke_mock.assert_any_call("notify_signed", {"signature_id": str(sig_id)})
    assert invoke_mock.call_count == 2


def test_failed_invokes_only_processes_signed(monkeypatch):
    invoke_mock = MagicMock()
    monkeypatch.setattr(sn, "invoke_async", invoke_mock)

    sig_id = uuid4()
    sn.notify_terminal_state(sig_id, "FAILED")

    args, kwargs = _signed_call(sig_id, "FAILED")
    invoke_mock.assert_called_once_with(*args, **kwargs)


def test_processes_signed_invoke_failure_does_not_raise(monkeypatch):
    invoke_mock = MagicMock(side_effect=LambdaInvokeError("signed", "boto_error", "boom"))
    monkeypatch.setattr(sn, "invoke_async", invoke_mock)

    # must not raise
    sn.notify_terminal_state(uuid4(), "FAILED")


def test_processes_signed_failure_does_not_block_notify_signed(monkeypatch):
    calls = []

    def fake_invoke(function_key, payload, service=None):
        calls.append(function_key)
        if function_key == "signed":
            raise LambdaInvokeError("signed", "boto_error", "boom")

    monkeypatch.setattr(sn, "invoke_async", fake_invoke)

    sn.notify_terminal_state(uuid4(), "SIGNED", notify_signer=True)

    assert calls == ["signed", "notify_signed"]


def test_notify_signed_invoke_failure_does_not_raise(monkeypatch):
    def fake_invoke(function_key, payload, service=None):
        if function_key == "notify_signed":
            raise LambdaInvokeError("notify_signed", "boto_error", "boom")

    monkeypatch.setattr(sn, "invoke_async", fake_invoke)

    # must not raise
    sn.notify_terminal_state(uuid4(), "SIGNED", notify_signer=True)
