"""Unit tests for the processes/generate_sign internal Lambda."""
from __future__ import annotations

import base64
import json
from decimal import Decimal
from unittest.mock import MagicMock
from urllib.parse import quote
from uuid import uuid4

import requests

_SIGN_LOCATION = [{"page": 1, "x_pct": 8.0, "y_pct": 80.0, "width_pct": 40.0, "height_pct": 14.0}]


def _process(stage="DOCUMENTS", **overrides):
    defaults = dict(
        id=uuid4(),
        stage=stage,
        bank_id=1,
        amount=Decimal("1000000.00"),
        term=180,
        rate=Decimal("12.50"),
        submitted_form={"name": "Ana", "last_name": "Gomez"},
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def _event(process_id):
    return {"body": json.dumps({"process_id": str(process_id)})}


def _files_response(status_code=200, body=None):
    body = body if body is not None else {
        "process_id": "p",
        "key": "processes/p/RAW_INVESTMENT_ORDER/x.pdf",
        "url": "https://files.test/signed-get",
        "sign_location": _SIGN_LOCATION,
    }
    return {"statusCode": status_code, "body": json.dumps(body)}


def _signature_response(signature_id, status_code=200):
    return {"statusCode": status_code, "body": json.dumps({"id": signature_id, "stage": "FORM"})}


def _patch(h, monkeypatch, process, **overrides):
    mocks = dict(
        Processes=MagicMock(get_by_id=MagicMock(return_value=process), set_signature_id=MagicMock()),
        invoke_sync=MagicMock(),
        requests=MagicMock(),
        send_email=MagicMock(return_value=True),
        _frontend_url=MagicMock(return_value="https://front.test"),
    )
    mocks.update(overrides)
    mocks["requests"].RequestException = requests.RequestException
    for name, mock in mocks.items():
        monkeypatch.setattr(h, name, mock)
    return mocks


def test_generate_sign_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)
    process = _process(submitted_form={"name": "Ana", "last_name": "Gomez", "email": "ana@example.com"})
    mocks = _patch(h, monkeypatch, process)
    mocks["requests"].get.return_value = MagicMock(content=b"%PDF-1.4 raw", raise_for_status=MagicMock())
    signature_id = str(uuid4())
    mocks["invoke_sync"].side_effect = [_files_response(), _signature_response(signature_id)]

    resp = h.handler(_event(process.id), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"process_id": str(process.id), "signature_id": signature_id, "email_sent": True}

    # 1st invoke: files.generate_raw_investment_order, standard body envelope.
    files_call = mocks["invoke_sync"].call_args_list[0]
    assert files_call.kwargs["function_key"] == "generate_raw_investment_order"
    assert files_call.kwargs["service"] == "files"
    assert json.loads(files_call.kwargs["payload"]["body"]) == {
        "process_id": str(process.id),
        "bank_id": 1,
        "submitted_form": process.submitted_form,
        "amount": "1000000.00",
        "term": 180,
        "rate": "12.50",
    }

    # The file to sign is the one files generated, fetched via its presigned URL.
    mocks["requests"].get.assert_called_once_with("https://files.test/signed-get", timeout=10)

    # 2nd invoke: signatures.create_signature with that exact document.
    sig_call = mocks["invoke_sync"].call_args_list[1]
    assert sig_call.kwargs["function_key"] == "create_signature"
    assert sig_call.kwargs["service"] == "signatures"
    event = sig_call.kwargs["payload"]
    assert base64.b64decode(event["body"]) == b"%PDF-1.4 raw"
    assert event["isBase64Encoded"] is True
    assert json.loads(event["queryStringParameters"]["sign_location"]) == _SIGN_LOCATION
    assert event["queryStringParameters"]["signatory"] == "Ana Gomez"

    mocks["Processes"].set_signature_id.assert_called_once_with(process.id, signature_id)


def test_generate_sign_emails_sign_link_to_form_email(load_handler, monkeypatch):
    h = load_handler(__file__)
    process = _process(submitted_form={"name": "Ana", "email": "ana@example.com"})
    mocks = _patch(h, monkeypatch, process)
    mocks["requests"].get.return_value = MagicMock(content=b"pdf", raise_for_status=MagicMock())
    signature_id = str(uuid4())
    mocks["invoke_sync"].side_effect = [_files_response(), _signature_response(signature_id)]

    resp = h.handler(_event(process.id), None)

    assert resp["statusCode"] == 200
    to, _subject, body = mocks["send_email"].call_args.args
    assert to == "ana@example.com"
    return_url = quote(f"https://front.test/portal/process/{process.id}", safe="")
    assert f"https://front.test/sign/{signature_id}?return_url={return_url}&amp;email=ana%40example.com" in body


def test_generate_sign_without_form_email_skips_mail_but_succeeds(load_handler, monkeypatch):
    h = load_handler(__file__)
    process = _process()
    mocks = _patch(h, monkeypatch, process)
    mocks["requests"].get.return_value = MagicMock(content=b"pdf", raise_for_status=MagicMock())
    mocks["invoke_sync"].side_effect = [_files_response(), _signature_response(str(uuid4()))]

    resp = h.handler(_event(process.id), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["email_sent"] is False
    mocks["send_email"].assert_not_called()


def test_generate_sign_mail_failure_does_not_fail_the_signature(load_handler, monkeypatch):
    h = load_handler(__file__)
    process = _process(submitted_form={"name": "Ana", "email": "ana@example.com"})
    mocks = _patch(h, monkeypatch, process, _frontend_url=MagicMock(side_effect=RuntimeError("ssm down")))
    mocks["requests"].get.return_value = MagicMock(content=b"pdf", raise_for_status=MagicMock())
    mocks["invoke_sync"].side_effect = [_files_response(), _signature_response(str(uuid4()))]

    resp = h.handler(_event(process.id), None)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["email_sent"] is False
    mocks["Processes"].set_signature_id.assert_called_once()


def test_generate_sign_signatory_falls_back_when_form_has_no_name(load_handler, monkeypatch):
    h = load_handler(__file__)
    process = _process(submitted_form={})
    mocks = _patch(h, monkeypatch, process)
    mocks["requests"].get.return_value = MagicMock(content=b"pdf", raise_for_status=MagicMock())
    mocks["invoke_sync"].side_effect = [_files_response(), _signature_response(str(uuid4()))]

    resp = h.handler(_event(process.id), None)

    assert resp["statusCode"] == 200
    event = mocks["invoke_sync"].call_args_list[1].kwargs["payload"]
    assert event["queryStringParameters"]["signatory"] == "Titular"


def test_generate_sign_signatory_name_skips_missing_parts(load_handler, monkeypatch):
    h = load_handler(__file__)

    assert h._signatory_name({"name": "Ana", "second_name": None, "last_name": "Gomez", "second_last_name": "Ruiz"}) == "Ana Gomez Ruiz"


def test_generate_sign_invalid_process_id(load_handler, monkeypatch):
    h = load_handler(__file__)
    mocks = _patch(h, monkeypatch, _process())

    resp = h.handler({"body": json.dumps({"process_id": "nope"})}, None)

    assert resp["statusCode"] == 400
    mocks["invoke_sync"].assert_not_called()


def test_generate_sign_missing_process_id(load_handler, monkeypatch):
    h = load_handler(__file__)
    mocks = _patch(h, monkeypatch, _process())

    resp = h.handler({"body": "{}"}, None)

    assert resp["statusCode"] == 400
    mocks["invoke_sync"].assert_not_called()


def test_generate_sign_process_not_found(load_handler, monkeypatch):
    h = load_handler(__file__)
    mocks = _patch(h, monkeypatch, None)

    resp = h.handler(_event(uuid4()), None)

    assert resp["statusCode"] == 404
    mocks["invoke_sync"].assert_not_called()


def test_generate_sign_wrong_stage_is_rejected(load_handler, monkeypatch):
    h = load_handler(__file__)
    process = _process(stage="SIGNATURE")
    mocks = _patch(h, monkeypatch, process)

    resp = h.handler(_event(process.id), None)

    assert resp["statusCode"] == 409
    mocks["invoke_sync"].assert_not_called()
    mocks["Processes"].set_signature_id.assert_not_called()


def test_generate_sign_files_error_is_propagated_and_nothing_is_stored(load_handler, monkeypatch):
    h = load_handler(__file__)
    process = _process()
    mocks = _patch(h, monkeypatch, process)
    mocks["invoke_sync"].side_effect = [_files_response(422, {"error": "bank_without_investment_order"})]

    resp = h.handler(_event(process.id), None)

    assert resp["statusCode"] == 422
    assert json.loads(resp["body"]) == {"error": "bank_without_investment_order"}
    assert mocks["invoke_sync"].call_count == 1
    mocks["Processes"].set_signature_id.assert_not_called()


def test_generate_sign_files_unreachable(load_handler, monkeypatch):
    h = load_handler(__file__)
    process = _process()
    mocks = _patch(h, monkeypatch, process)
    mocks["invoke_sync"].side_effect = h.LambdaInvokeError("fn", "boto_error", "timeout")

    resp = h.handler(_event(process.id), None)

    assert resp["statusCode"] == 502
    assert json.loads(resp["body"]) == {"error": "files_unavailable"}
    mocks["Processes"].set_signature_id.assert_not_called()


def test_generate_sign_download_failure(load_handler, monkeypatch):
    h = load_handler(__file__)
    process = _process()
    mocks = _patch(h, monkeypatch, process)
    mocks["invoke_sync"].side_effect = [_files_response()]
    mocks["requests"].get.side_effect = requests.ConnectionError("down")

    resp = h.handler(_event(process.id), None)

    assert resp["statusCode"] == 502
    assert json.loads(resp["body"]) == {"error": "investment_order_download_failed"}
    assert mocks["invoke_sync"].call_count == 1
    mocks["Processes"].set_signature_id.assert_not_called()


def test_generate_sign_create_signature_failure_leaves_process_untouched(load_handler, monkeypatch):
    h = load_handler(__file__)
    process = _process()
    mocks = _patch(h, monkeypatch, process)
    mocks["requests"].get.return_value = MagicMock(content=b"pdf", raise_for_status=MagicMock())
    mocks["invoke_sync"].side_effect = [_files_response(), _signature_response("x", status_code=500)]

    resp = h.handler(_event(process.id), None)

    assert resp["statusCode"] == 500
    mocks["Processes"].set_signature_id.assert_not_called()
