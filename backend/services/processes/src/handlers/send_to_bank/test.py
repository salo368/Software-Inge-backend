"""Unit tests for the processes/send_to_bank Lambda (backoffice, admin only)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import UUID

_PID = "7077c70e-d8bf-4c8e-97ef-a7e0909949df"


def _patch_admin_auth(monkeypatch):
    monkeypatch.setattr(
        "libs.utils.auth.AdminBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None, admin_id="a-1"))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Admins", MagicMock(get_by_id=MagicMock(return_value=MagicMock(id="a-1"))))


def _event(body=None):
    event = {"headers": {"Authorization": "Bearer adm"}}
    if body is not None:
        event["body"] = json.dumps(body)
    return event


def _patch_processes(h, monkeypatch, stage="REVIEW", found=True):
    process = MagicMock(id=UUID(_PID), stage=stage) if found else None
    processes = MagicMock(
        get_by_id_for_update=MagicMock(return_value=process),
        advance_to_sent_to_bank=MagicMock(return_value=MagicMock(stage="SENT_TO_BANK")),
    )
    monkeypatch.setattr(h, "Processes", processes)
    return processes


def test_send_to_bank_moves_review_to_sent_to_bank(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    processes = _patch_processes(h, monkeypatch)

    resp = h.handler(_event({"process_id": _PID}), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"process_id": _PID, "stage": "SENT_TO_BANK"}
    processes.get_by_id_for_update.assert_called_once_with(UUID(_PID))
    processes.advance_to_sent_to_bank.assert_called_once_with(UUID(_PID))


def test_send_to_bank_only_from_review(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)

    for stage in ("FORM", "DOCUMENTS", "SIGNATURE", "PAYMENT", "SENT_TO_BANK", "COMPLETED"):
        processes = _patch_processes(h, monkeypatch, stage=stage)

        resp = h.handler(_event({"process_id": _PID}), None)

        assert resp["statusCode"] == 409, stage
        assert json.loads(resp["body"]) == {"error": "process_not_in_review_stage"}
        processes.advance_to_sent_to_bank.assert_not_called()


def test_send_to_bank_process_not_found(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    processes = _patch_processes(h, monkeypatch, found=False)

    resp = h.handler(_event({"process_id": _PID}), None)

    assert resp["statusCode"] == 404
    processes.advance_to_sent_to_bank.assert_not_called()


def test_send_to_bank_invalid_process_id(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_admin_auth(monkeypatch)
    processes = _patch_processes(h, monkeypatch)

    for event in (_event(), _event({"process_id": "nope"})):
        resp = h.handler(event, None)

        assert resp["statusCode"] == 400
        assert json.loads(resp["body"]) == {"error": "invalid process id"}
    processes.get_by_id_for_update.assert_not_called()


def test_send_to_bank_user_token_is_rejected(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr("libs.utils.auth.AdminBearerTokens", MagicMock(get_by_hash=MagicMock(return_value=None)))
    processes = _patch_processes(h, monkeypatch)

    resp = h.handler(_event({"process_id": _PID}), None)

    assert resp["statusCode"] == 401
    processes.advance_to_sent_to_bank.assert_not_called()


def test_send_to_bank_requires_auth(load_handler):
    h = load_handler(__file__)

    resp = h.handler({"headers": {}}, None)

    assert resp["statusCode"] == 401
