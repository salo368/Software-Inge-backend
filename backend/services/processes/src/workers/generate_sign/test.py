"""Unit tests for the processes/generate_sign internal worker."""
from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4


def _process(stage="DOCUMENTS", **overrides):
    defaults = dict(
        id=str(uuid4()),
        stage=stage,
        bank_id=1,
        amount=Decimal("1000000.00"),
        term=180,
        rate=Decimal("12.50"),
        submitted_form={"name": "Ana", "last_name": "Gomez"},
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def _bank_response(io_url="https://assets.test/order-forms/bancolombia.pdf", status_code=200):
    return {"statusCode": status_code, "body": json.dumps({"id": 1, "name": "Bancolombia", "io_url": io_url})}


def _create_signature_response(signature_id, status_code=200):
    return {"statusCode": status_code, "body": json.dumps({"id": signature_id, "stage": "FORM"})}


def _patch_pipeline(h, monkeypatch, **overrides):
    mocks = dict(
        invoke_sync=MagicMock(),
        requests=MagicMock(),
        populate_investment_order=MagicMock(return_value=b"%PDF-1.4 populated"),
        db_session=MagicMock(),
    )
    mocks.update(overrides)
    for name, mock in mocks.items():
        monkeypatch.setattr(h, name, mock)
    return mocks


def test_generate_sign_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)

    process = _process()
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=process), set_signature_id=MagicMock())
    monkeypatch.setattr(h, "Processes", signatures_mock)

    new_signature_id = str(uuid4())
    mocks = _patch_pipeline(h, monkeypatch)
    mocks["requests"].get.return_value = MagicMock(content=b"%PDF-1.4 template", raise_for_status=MagicMock())
    mocks["invoke_sync"].side_effect = [
        _bank_response(),
        _create_signature_response(new_signature_id),
    ]

    result = h.handler({"process_id": process.id}, None)

    assert result == {"ok": True, "process_id": process.id, "signature_id": new_signature_id}

    # 1st invoke: banks.get_bank with the process's bank_id.
    bank_call = mocks["invoke_sync"].call_args_list[0]
    assert bank_call.args[0] == "get_bank"
    assert bank_call.args[1] == {"queryStringParameters": {"bank_id": "1"}}
    assert bank_call.kwargs["service"] == "banks"

    # Template fetched from the URL get_bank returned.
    mocks["requests"].get.assert_called_once_with(
        "https://assets.test/order-forms/bancolombia.pdf", timeout=10,
    )

    # populate_investment_order gets the process's form + commercial terms.
    mocks["populate_investment_order"].assert_called_once_with(
        b"%PDF-1.4 template", form=process.submitted_form, amount=process.amount,
        term=process.term, rate=process.rate,
    )

    # 2nd invoke: signatures.create_signature with the populated PDF as a
    # base64 body and the shared SIGNATURE_LOCATION.
    sign_call = mocks["invoke_sync"].call_args_list[1]
    assert sign_call.args[0] == "create_signature"
    assert sign_call.kwargs["service"] == "signatures"
    event = sign_call.args[1]
    assert event["isBase64Encoded"] is True
    import base64
    assert base64.b64decode(event["body"]) == b"%PDF-1.4 populated"
    assert json.loads(event["queryStringParameters"]["sign_location"]) == h.SIGNATURE_LOCATION
    assert event["queryStringParameters"]["signatory"] == "Ana Gomez"

    signatures_mock.set_signature_id.assert_called_once_with(process.id, new_signature_id)
    mocks["db_session"].commit.assert_called_once()
    mocks["db_session"].rollback.assert_not_called()


def test_generate_sign_missing_process_id_short_circuits(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(side_effect=AssertionError)))

    result = h.handler({}, None)

    assert result == {"ok": False, "error": "missing_process_id"}


def test_generate_sign_process_not_found(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h, "Processes", MagicMock(get_by_id=MagicMock(return_value=None)))

    result = h.handler({"process_id": str(uuid4())}, None)

    assert result == {"ok": False, "error": "process_not_found"}


def test_generate_sign_wrong_stage_is_skipped(load_handler, monkeypatch):
    h = load_handler(__file__)

    process = _process(stage="SIGNATURE")
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=process), set_signature_id=MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Processes", signatures_mock)
    monkeypatch.setattr(h, "invoke_sync", MagicMock(side_effect=AssertionError))

    result = h.handler({"process_id": process.id}, None)

    assert result == {"ok": False, "skipped": True, "stage": "SIGNATURE"}
    signatures_mock.set_signature_id.assert_not_called()


def test_generate_sign_bank_lookup_failure_does_not_crash(load_handler, monkeypatch):
    h = load_handler(__file__)

    process = _process()
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=process), set_signature_id=MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Processes", signatures_mock)
    mocks = _patch_pipeline(h, monkeypatch)
    mocks["invoke_sync"].side_effect = [_bank_response(status_code=404)]

    result = h.handler({"process_id": process.id}, None)

    assert result == {"ok": False, "error": "internal_error"}
    signatures_mock.set_signature_id.assert_not_called()
    mocks["db_session"].rollback.assert_called_once()
    mocks["db_session"].commit.assert_not_called()


def test_generate_sign_bank_without_io_url_does_not_crash(load_handler, monkeypatch):
    h = load_handler(__file__)

    process = _process()
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=process), set_signature_id=MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Processes", signatures_mock)
    mocks = _patch_pipeline(h, monkeypatch)
    mocks["invoke_sync"].side_effect = [_bank_response(io_url=None)]

    result = h.handler({"process_id": process.id}, None)

    assert result == {"ok": False, "error": "internal_error"}
    signatures_mock.set_signature_id.assert_not_called()


def test_generate_sign_template_download_failure_does_not_crash(load_handler, monkeypatch):
    h = load_handler(__file__)

    process = _process()
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=process), set_signature_id=MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Processes", signatures_mock)
    mocks = _patch_pipeline(h, monkeypatch)
    mocks["invoke_sync"].side_effect = [_bank_response()]
    mocks["requests"].get.return_value = MagicMock(
        content=b"", raise_for_status=MagicMock(side_effect=RuntimeError("404 on asset")),
    )

    result = h.handler({"process_id": process.id}, None)

    assert result == {"ok": False, "error": "internal_error"}
    signatures_mock.set_signature_id.assert_not_called()


def test_generate_sign_create_signature_failure_does_not_crash(load_handler, monkeypatch):
    h = load_handler(__file__)

    process = _process()
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=process), set_signature_id=MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(h, "Processes", signatures_mock)
    mocks = _patch_pipeline(h, monkeypatch)
    mocks["requests"].get.return_value = MagicMock(content=b"%PDF-1.4", raise_for_status=MagicMock())
    mocks["invoke_sync"].side_effect = [_bank_response(), _create_signature_response("ignored", status_code=502)]

    result = h.handler({"process_id": process.id}, None)

    assert result == {"ok": False, "error": "internal_error"}
    signatures_mock.set_signature_id.assert_not_called()
    mocks["db_session"].rollback.assert_called_once()


def test_generate_sign_signatory_name_skips_missing_parts(load_handler, monkeypatch):
    h = load_handler(__file__)

    process = _process(submitted_form={"name": "Ana", "second_name": None, "last_name": "Gomez", "second_last_name": None})
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=process), set_signature_id=MagicMock())
    monkeypatch.setattr(h, "Processes", signatures_mock)
    mocks = _patch_pipeline(h, monkeypatch)
    mocks["requests"].get.return_value = MagicMock(content=b"%PDF-1.4", raise_for_status=MagicMock())
    mocks["invoke_sync"].side_effect = [_bank_response(), _create_signature_response(str(uuid4()))]

    h.handler({"process_id": process.id}, None)

    sign_call = mocks["invoke_sync"].call_args_list[1]
    assert sign_call.args[1]["queryStringParameters"]["signatory"] == "Ana Gomez"


def test_generate_sign_signatory_falls_back_when_form_has_no_name(load_handler, monkeypatch):
    h = load_handler(__file__)

    process = _process(submitted_form={})
    signatures_mock = MagicMock(get_by_id=MagicMock(return_value=process), set_signature_id=MagicMock())
    monkeypatch.setattr(h, "Processes", signatures_mock)
    mocks = _patch_pipeline(h, monkeypatch)
    mocks["requests"].get.return_value = MagicMock(content=b"%PDF-1.4", raise_for_status=MagicMock())
    mocks["invoke_sync"].side_effect = [_bank_response(), _create_signature_response(str(uuid4()))]

    h.handler({"process_id": process.id}, None)

    sign_call = mocks["invoke_sync"].call_args_list[1]
    assert sign_call.args[1]["queryStringParameters"]["signatory"] == "Titular"
