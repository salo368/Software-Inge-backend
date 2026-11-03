"""Unit tests for the signatures check_signature_timeout worker."""
from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import uuid4


def _sqs_event(*signature_ids) -> dict:
    return {
        "Records": [
            {"body": json.dumps({"signature_id": str(sig_id)})}
            for sig_id in signature_ids
        ]
    }


def test_marks_unsigned_signature_as_failed(load_handler, monkeypatch):
    h = load_handler(__file__)

    sig_id = uuid4()
    row = MagicMock(stage="BIOMETRICS")
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row), mark_failed=MagicMock())
    monkeypatch.setattr(h, "Signatures", signatures_mock)

    call_order = []
    db_session_mock = MagicMock()
    db_session_mock.commit.side_effect = lambda: call_order.append("commit")
    monkeypatch.setattr(h, "db_session", db_session_mock)
    notify_mock = MagicMock(side_effect=lambda *a: call_order.append("notify"))
    monkeypatch.setattr(h, "notify_terminal_state", notify_mock)

    result = h.handler(_sqs_event(sig_id), None)

    signatures_mock.mark_failed.assert_called_once_with(str(sig_id))
    assert result == {"processed": 1}
    notify_mock.assert_called_once_with(str(sig_id), "FAILED")
    # Notification must fire only after the batch commit, never before --
    # it would be wrong to notify about a write that may not have persisted.
    assert call_order == ["commit", "notify"]


def test_does_not_touch_already_signed(load_handler, monkeypatch):
    h = load_handler(__file__)

    sig_id = uuid4()
    row = MagicMock(stage="SIGNED")
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row), mark_failed=MagicMock())
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    monkeypatch.setattr(h, "db_session", MagicMock())
    notify_mock = MagicMock()
    monkeypatch.setattr(h, "notify_terminal_state", notify_mock)

    h.handler(_sqs_event(sig_id), None)

    signatures_mock.mark_failed.assert_not_called()
    notify_mock.assert_not_called()


def test_does_not_touch_already_failed(load_handler, monkeypatch):
    h = load_handler(__file__)

    sig_id = uuid4()
    row = MagicMock(stage="FAILED")
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row), mark_failed=MagicMock())
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    monkeypatch.setattr(h, "db_session", MagicMock())
    notify_mock = MagicMock()
    monkeypatch.setattr(h, "notify_terminal_state", notify_mock)

    h.handler(_sqs_event(sig_id), None)

    signatures_mock.mark_failed.assert_not_called()
    notify_mock.assert_not_called()


def test_does_not_touch_signing(load_handler, monkeypatch):
    h = load_handler(__file__)

    sig_id = uuid4()
    row = MagicMock(stage="SIGNING")
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row), mark_failed=MagicMock())
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    monkeypatch.setattr(h, "db_session", MagicMock())
    notify_mock = MagicMock()
    monkeypatch.setattr(h, "notify_terminal_state", notify_mock)

    h.handler(_sqs_event(sig_id), None)

    signatures_mock.mark_failed.assert_not_called()
    notify_mock.assert_not_called()


def test_missing_signature_does_not_raise(load_handler, monkeypatch):
    h = load_handler(__file__)

    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=None), mark_failed=MagicMock())
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    monkeypatch.setattr(h, "db_session", MagicMock())
    notify_mock = MagicMock()
    monkeypatch.setattr(h, "notify_terminal_state", notify_mock)

    result = h.handler(_sqs_event(uuid4()), None)

    signatures_mock.mark_failed.assert_not_called()
    assert result == {"processed": 1}
    notify_mock.assert_not_called()


def test_one_bad_record_does_not_block_the_rest(load_handler, monkeypatch):
    h = load_handler(__file__)

    good_id = uuid4()
    row = MagicMock(stage="OTP")
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row), mark_failed=MagicMock())
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    monkeypatch.setattr(h, "db_session", MagicMock())
    notify_mock = MagicMock()
    monkeypatch.setattr(h, "notify_terminal_state", notify_mock)

    event = {"Records": [{"body": "not-json"}, {"body": json.dumps({"signature_id": str(good_id)})}]}
    result = h.handler(event, None)

    signatures_mock.mark_failed.assert_called_once_with(str(good_id))
    assert result == {"processed": 2}
    notify_mock.assert_called_once_with(str(good_id), "FAILED")
