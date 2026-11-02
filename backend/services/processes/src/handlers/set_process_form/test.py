"""Unit tests for the processes/set_process_form Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import UUID


def _authed_event(process_id: str, headers: dict | None = None) -> dict:
    return {
        "headers": headers if headers is not None else {"Authorization": "Bearer tok"},
        "body": json.dumps({"process_id": process_id}),
    }


def _patch_auth(monkeypatch, user_id="u-1"):
    user = MagicMock(id=user_id)
    monkeypatch.setattr(
        "libs.utils.auth.BearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Users", MagicMock(get_by_id=MagicMock(return_value=user)))
    return user


def _get_form_response(form, status_code=200):
    return {"statusCode": status_code, "body": json.dumps({"form": form})}


_PID = "7077c70e-d8bf-4c8e-97ef-a7e0909949df"


def test_set_process_form_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch, user_id=_PID)

    process = MagicMock(id=_PID, user_id=user.id)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=process)))

    form = {"name": "FOO", "document_number": "123"}
    monkeypatch.setattr(h, "invoke_sync", MagicMock(return_value=_get_form_response(form)))

    updated = MagicMock(id=_PID, stage="DOCUMENTS", submitted_form=form)
    h.Processes.set_submitted_form = MagicMock(return_value=updated)

    resp = h.handler(_authed_event(_PID), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"id": _PID, "stage": "DOCUMENTS", "submitted_form": form}
    h.Processes.set_submitted_form.assert_called_once_with(UUID(_PID), form)


def test_set_process_form_invalid_process_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_authed_event("not-a-uuid"), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid process id"}


def test_set_process_form_not_found_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=None)))

    resp = h.handler(_authed_event(_PID), None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "process_not_found"}


def test_set_process_form_other_users_process_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch, user_id="u-1")

    process = MagicMock(id=_PID, user_id="someone-else")
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=process)))

    resp = h.handler(_authed_event(_PID), None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "process_not_found"}


def test_set_process_form_missing_form_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch, user_id=_PID)

    process = MagicMock(id=_PID, user_id=user.id)
    monkeypatch.setattr(
        h, "Processes", MagicMock(get_by_id=MagicMock(return_value=process), set_submitted_form=MagicMock(side_effect=AssertionError))
    )
    monkeypatch.setattr(h, "invoke_sync", MagicMock(return_value=_get_form_response(None)))

    resp = h.handler(_authed_event(_PID), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "form_required"}


def test_set_process_form_invoke_failure_returns_502(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch, user_id=_PID)

    process = MagicMock(id=_PID, user_id=user.id)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=process)))
    monkeypatch.setattr(
        h,
        "invoke_sync",
        MagicMock(side_effect=h.LambdaInvokeError("cdts-test-forms-get-form", "boto_error", "timeout")),
    )

    resp = h.handler(_authed_event(_PID), None)

    assert resp["statusCode"] == 502
    assert json.loads(resp["body"]) == {"error": "form_lookup_unavailable"}


def test_set_process_form_forwards_auth_header_to_get_form(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch, user_id=_PID)

    process = MagicMock(id=_PID, user_id=user.id)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=process)))

    invoke_mock = MagicMock(return_value=_get_form_response({"name": "FOO"}))
    monkeypatch.setattr(h, "invoke_sync", invoke_mock)
    h.Processes.set_submitted_form = MagicMock(
        return_value=MagicMock(id=_PID, stage="DOCUMENTS", submitted_form={"name": "FOO"})
    )

    headers = {"Authorization": "Bearer tok"}
    h.handler(_authed_event(_PID, headers=headers), None)

    _, kwargs = invoke_mock.call_args
    assert kwargs["function_key"] == "get_form"
    assert kwargs["service"] == "forms"
    assert kwargs["payload"]["headers"] == headers


def test_set_process_form_requires_auth(load_handler):
    h = load_handler(__file__)

    resp = h.handler({"headers": {}, "body": json.dumps({"process_id": _PID})}, None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "missing_bearer_token"}
