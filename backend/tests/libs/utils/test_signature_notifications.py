"""Unit tests for `libs.utils.signature_notifications`."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from libs.utils import signature_notifications as sn
from libs.utils.lambda_invoke import LambdaInvokeError


def test_signed_invokes_both_sign_trigger_and_notify_signed(monkeypatch):
    invoke_mock = MagicMock()
    monkeypatch.setattr(sn, "invoke_async", invoke_mock)

    sig_id = uuid4()
    sn.notify_terminal_state(sig_id, "SIGNED", notify_signer=True)

    invoke_mock.assert_any_call("sign_trigger", {"signature_id": str(sig_id), "stage": "SIGNED"})
    invoke_mock.assert_any_call("notify_signed", {"signature_id": str(sig_id)})
    assert invoke_mock.call_count == 2


def test_failed_invokes_only_sign_trigger(monkeypatch):
    invoke_mock = MagicMock()
    monkeypatch.setattr(sn, "invoke_async", invoke_mock)

    sig_id = uuid4()
    sn.notify_terminal_state(sig_id, "FAILED")

    invoke_mock.assert_called_once_with("sign_trigger", {"signature_id": str(sig_id), "stage": "FAILED"})


def test_sign_trigger_invoke_failure_does_not_raise(monkeypatch):
    invoke_mock = MagicMock(side_effect=LambdaInvokeError("sign_trigger", "boto_error", "boom"))
    monkeypatch.setattr(sn, "invoke_async", invoke_mock)

    # must not raise
    sn.notify_terminal_state(uuid4(), "FAILED")


def test_notify_signed_invoke_failure_does_not_raise_and_does_not_block_sign_trigger(monkeypatch):
    calls = []

    def fake_invoke(function_key, payload):
        calls.append(function_key)
        if function_key == "notify_signed":
            raise LambdaInvokeError("notify_signed", "boto_error", "boom")

    monkeypatch.setattr(sn, "invoke_async", fake_invoke)

    sn.notify_terminal_state(uuid4(), "SIGNED", notify_signer=True)

    assert calls == ["sign_trigger", "notify_signed"]
