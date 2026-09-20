"""Unit tests for the processes/advance Lambda."""
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


def _proc(user_id: str, stage: str):
    return MagicMock(
        id=uuid4(),
        user_id=user_id,
        stage=stage,
        form_snapshot=None,
        advance_to=MagicMock(),
        public_dict=MagicMock(return_value={"stage": stage}),
    )


def test_advance_from_form_snapshots_form_and_advances(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    proc = _proc(user.id, "form")
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))
    monkeypatch.setattr(
        h,
        "Forms",
        MagicMock(get_by_user=MagicMock(return_value=MagicMock(
            public_dict=MagicMock(return_value={"full_name": "Foo"})
        ))),
    )

    resp = h.handler(_authed_event(str(uuid4())), None)

    assert resp["statusCode"] == 200
    assert proc.form_snapshot == {"full_name": "Foo"}
    proc.advance_to.assert_called_once_with("documents")


def test_advance_from_form_without_form_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    proc = _proc(user.id, "form")
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))
    monkeypatch.setattr(h, "Forms", MagicMock(get_by_user=MagicMock(return_value=None)))

    resp = h.handler(_authed_event(str(uuid4())), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "form_required"}
    proc.advance_to.assert_not_called()


def test_advance_when_done_is_idempotent(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch)

    proc = _proc(user.id, "done")
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=proc)))

    resp = h.handler(_authed_event(str(uuid4())), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"process": {"stage": "done"}}
    proc.advance_to.assert_not_called()
