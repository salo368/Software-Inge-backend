"""Unit tests for the processes/get Lambda."""
from __future__ import annotations

import json
from uuid import uuid4
from unittest.mock import MagicMock


def _authed_event(pid: str) -> dict:
    return {"headers": {"Authorization": "Bearer tok"}, "pathParameters": {"id": pid}}


def _patch_auth(monkeypatch, user_id="u-1"):
    user = MagicMock(id=user_id)
    monkeypatch.setattr(
        "libs.utils.auth.verify_token",
        MagicMock(return_value=(user, MagicMock())),
    )
    return user


def test_processes_get_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    pid = uuid4()
    proc = MagicMock(
        id=pid,
        user_id=user.id,
        public_dict=MagicMock(return_value={"id": str(pid), "stage": "form"}),
    )
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))
    monkeypatch.setattr(
        h,
        "Files",
        MagicMock(list_by_process=MagicMock(return_value=[
            MagicMock(public_dict=MagicMock(return_value={"id": "f-1"}))
        ])),
    )
    monkeypatch.setattr(
        h,
        "Signatures",
        MagicMock(get_active_for_process=MagicMock(return_value=None)),
    )

    resp = h.handler(_authed_event(str(pid)), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["process"] == {"id": str(pid), "stage": "form"}
    assert body["files"] == [{"id": "f-1"}]
    assert body["signature"] is None


def test_processes_get_invalid_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_authed_event("not-a-uuid"), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid process id"}


def test_processes_get_of_other_user_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch, user_id="me")

    proc = MagicMock(user_id="someone-else", public_dict=MagicMock(return_value={}))
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))
    monkeypatch.setattr(h, "Files", MagicMock(list_by_process=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_authed_event(str(uuid4())), None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "process_not_found"}
