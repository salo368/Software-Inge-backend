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


def test_processes_get_happy_path_no_ceremony(load_handler, monkeypatch):
    """Process has no sign_id yet (pre-signature stages). Handler must
    return signature=None without invoking Signatures at all."""
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    pid = uuid4()
    proc = MagicMock(
        id=pid,
        user_id=user.id,
        sign_id=None,
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
    signatures_mock = MagicMock(get_by_sign_id=MagicMock(return_value=None))
    monkeypatch.setattr(h, "Signatures", signatures_mock)

    resp = h.handler(_authed_event(str(pid)), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["process"] == {"id": str(pid), "stage": "form"}
    assert body["files"] == [{"id": "f-1"}]
    assert body["signature"] is None
    # We didn't call the ORM at all, since sign_id was None -- avoids
    # a needless DB round trip on early-stage processes.
    signatures_mock.get_by_sign_id.assert_not_called()


def test_processes_get_happy_path_with_ceremony(load_handler, monkeypatch):
    """Process has sign_id set (post-fase-6a). Handler must resolve
    the ceremony via get_by_sign_id and embed its public_dict."""
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    pid = uuid4()
    proc = MagicMock(
        id=pid,
        user_id=user.id,
        sign_id="sign_xyz",
        public_dict=MagicMock(return_value={"id": str(pid), "stage": "signature"}),
    )
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))
    monkeypatch.setattr(
        h,
        "Files",
        MagicMock(list_by_process=MagicMock(return_value=[])),
    )
    ceremony = MagicMock(
        public_dict=MagicMock(return_value={"sign_id": "sign_xyz", "stage": "otp"})
    )
    monkeypatch.setattr(
        h,
        "Signatures",
        MagicMock(get_by_sign_id=MagicMock(return_value=ceremony)),
    )

    resp = h.handler(_authed_event(str(pid)), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["signature"] == {"sign_id": "sign_xyz", "stage": "otp"}
    h.Signatures.get_by_sign_id.assert_called_once_with("sign_xyz")


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
