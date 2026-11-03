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
    monkeypatch.setattr(h, "db_session", MagicMock())

    result = h.handler(_sqs_event(sig_id), None)

    signatures_mock.mark_failed.assert_called_once_with(str(sig_id))
    assert result == {"processed": 1}


def test_does_not_touch_already_signed(load_handler, monkeypatch):
    h = load_handler(__file__)

    sig_id = uuid4()
    row = MagicMock(stage="SIGNED")
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row), mark_failed=MagicMock())
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    monkeypatch.setattr(h, "db_session", MagicMock())

    h.handler(_sqs_event(sig_id), None)

    signatures_mock.mark_failed.assert_not_called()


def test_does_not_touch_already_failed(load_handler, monkeypatch):
    h = load_handler(__file__)

    sig_id = uuid4()
    row = MagicMock(stage="FAILED")
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row), mark_failed=MagicMock())
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    monkeypatch.setattr(h, "db_session", MagicMock())

    h.handler(_sqs_event(sig_id), None)

    signatures_mock.mark_failed.assert_not_called()


def test_does_not_touch_signing(load_handler, monkeypatch):
    h = load_handler(__file__)

    sig_id = uuid4()
    row = MagicMock(stage="SIGNING")
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row), mark_failed=MagicMock())
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    monkeypatch.setattr(h, "db_session", MagicMock())

    h.handler(_sqs_event(sig_id), None)

    signatures_mock.mark_failed.assert_not_called()


def test_missing_signature_does_not_raise(load_handler, monkeypatch):
    h = load_handler(__file__)

    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=None), mark_failed=MagicMock())
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    monkeypatch.setattr(h, "db_session", MagicMock())

    result = h.handler(_sqs_event(uuid4()), None)

    signatures_mock.mark_failed.assert_not_called()
    assert result == {"processed": 1}


def test_one_bad_record_does_not_block_the_rest(load_handler, monkeypatch):
    h = load_handler(__file__)

    good_id = uuid4()
    row = MagicMock(stage="OTP")
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=row), mark_failed=MagicMock())
    monkeypatch.setattr(h, "Signatures", signatures_mock)
    monkeypatch.setattr(h, "db_session", MagicMock())

    event = {"Records": [{"body": "not-json"}, {"body": json.dumps({"signature_id": str(good_id)})}]}
    result = h.handler(event, None)

    signatures_mock.mark_failed.assert_called_once_with(str(good_id))
    assert result == {"processed": 2}
