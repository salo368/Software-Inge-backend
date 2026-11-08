"""Unit tests for the processes/get_required_files Lambda."""
from __future__ import annotations

import json
from unittest.mock import MagicMock
from uuid import UUID


def _authed_event(process_id: str) -> dict:
    return {
        "headers": {"Authorization": "Bearer tok"},
        "queryStringParameters": {"process_id": process_id},
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


def _list_files_response(files, status_code=200):
    return {"statusCode": status_code, "body": json.dumps({"files": files})}


_PID = "7077c70e-d8bf-4c8e-97ef-a7e0909949df"


def _fake_process(submitted_form, user_id, stage="DOCUMENTS"):
    return MagicMock(id=UUID(_PID), user_id=user_id, submitted_form=submitted_form, stage=stage)


def test_get_required_files_bank_cert_always_required(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch, user_id=_PID)

    process = _fake_process({"is_tax_declarant": False, "is_pep": False}, user.id)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=process)))
    monkeypatch.setattr(h, "invoke_sync", MagicMock(return_value=_list_files_response([])))
    monkeypatch.setattr(h, "invoke_async", MagicMock(side_effect=AssertionError("should not generate_sign")))

    resp = h.handler(_authed_event(_PID), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"BANK_CERT": False}


def test_get_required_files_tax_declaration_required_when_declarant(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch, user_id=_PID)

    process = _fake_process({"is_tax_declarant": True, "is_pep": False}, user.id)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=process)))
    monkeypatch.setattr(
        h,
        "invoke_sync",
        MagicMock(return_value=_list_files_response([{"file_type": "BANK_CERT"}])),
    )
    monkeypatch.setattr(h, "invoke_async", MagicMock(side_effect=AssertionError("should not generate_sign")))

    resp = h.handler(_authed_event(_PID), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"BANK_CERT": True, "TAX_DECLARATION": False}


def test_get_required_files_rut_required_when_pep(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch, user_id=_PID)

    process = _fake_process({"is_tax_declarant": False, "is_pep": True}, user.id)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=process)))
    monkeypatch.setattr(h, "invoke_sync", MagicMock(return_value=_list_files_response([])))
    monkeypatch.setattr(h, "invoke_async", MagicMock(side_effect=AssertionError("should not generate_sign")))

    resp = h.handler(_authed_event(_PID), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"BANK_CERT": False, "RUT": False}


def test_get_required_files_all_satisfied_triggers_generate_sign(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch, user_id=_PID)

    process = _fake_process({"is_tax_declarant": True, "is_pep": True}, user.id)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=process)))
    monkeypatch.setattr(
        h,
        "invoke_sync",
        MagicMock(
            return_value=_list_files_response(
                [{"file_type": "BANK_CERT"}, {"file_type": "TAX_DECLARATION"}, {"file_type": "RUT"}]
            )
        ),
    )
    invoke_async_mock = MagicMock()
    monkeypatch.setattr(h, "invoke_async", invoke_async_mock)

    resp = h.handler(_authed_event(_PID), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"BANK_CERT": True, "TAX_DECLARATION": True, "RUT": True}
    invoke_async_mock.assert_called_once_with(
        "generate_sign", {"body": json.dumps({"process_id": _PID})},
    )


def test_get_required_files_satisfied_but_already_past_documents_does_not_retrigger(load_handler, monkeypatch):
    """A process already in SIGNATURE (or later) must not spawn a second
    signature ceremony just because the caller polls again."""
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch, user_id=_PID)

    process = _fake_process({"is_tax_declarant": False, "is_pep": False}, user.id, stage="SIGNATURE")
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=process)))
    monkeypatch.setattr(
        h, "invoke_sync", MagicMock(return_value=_list_files_response([{"file_type": "BANK_CERT"}]))
    )
    monkeypatch.setattr(h, "invoke_async", MagicMock(side_effect=AssertionError("should not generate_sign")))

    resp = h.handler(_authed_event(_PID), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"BANK_CERT": True}


def test_get_required_files_generate_sign_invoke_failure_returns_502(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch, user_id=_PID)

    process = _fake_process({"is_tax_declarant": False, "is_pep": False}, user.id)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=process)))
    monkeypatch.setattr(
        h, "invoke_sync", MagicMock(return_value=_list_files_response([{"file_type": "BANK_CERT"}]))
    )
    monkeypatch.setattr(
        h,
        "invoke_async",
        MagicMock(side_effect=h.LambdaInvokeError("cdts-test-processes-generate-sign", "boto_error", "boom")),
    )

    resp = h.handler(_authed_event(_PID), None)

    assert resp["statusCode"] == 502
    assert json.loads(resp["body"]) == {"error": "generate_sign_unavailable"}


def test_get_required_files_missing_submitted_form_defaults_to_bank_cert_only(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch, user_id=_PID)

    process = _fake_process(None, user.id)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=process)))
    monkeypatch.setattr(h, "invoke_sync", MagicMock(return_value=_list_files_response([])))
    monkeypatch.setattr(h, "invoke_async", MagicMock(side_effect=AssertionError("should not generate_sign")))

    resp = h.handler(_authed_event(_PID), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"BANK_CERT": False}


def test_get_required_files_invalid_process_id_returns_400(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    resp = h.handler(_authed_event("not-a-uuid"), None)

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"]) == {"error": "invalid process id"}


def test_get_required_files_other_users_process_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch, user_id="u-1")

    process = _fake_process({}, "someone-else")
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=process)))

    resp = h.handler(_authed_event(_PID), None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "process_not_found"}


def test_get_required_files_invoke_failure_returns_502(load_handler, monkeypatch):
    h = load_handler(__file__)
    user = _patch_auth(monkeypatch, user_id=_PID)

    process = _fake_process({}, user.id)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=process)))
    monkeypatch.setattr(
        h,
        "invoke_sync",
        MagicMock(side_effect=h.LambdaInvokeError("cdts-test-files-list-process-files", "boto_error", "timeout")),
    )

    resp = h.handler(_authed_event(_PID), None)

    assert resp["statusCode"] == 502
    assert json.loads(resp["body"]) == {"error": "files_lookup_unavailable"}


def test_get_required_files_requires_auth(load_handler):
    h = load_handler(__file__)

    resp = h.handler({"headers": {}, "queryStringParameters": {"process_id": _PID}}, None)

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"]) == {"error": "missing_bearer_token"}
