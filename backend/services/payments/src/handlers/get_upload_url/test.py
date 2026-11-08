"""Unit tests for the payments/get_upload_url Lambda."""
from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock

from libs.utils.lambda_invoke import LambdaInvokeError

_PID = "7077c70e-d8bf-4c8e-97ef-a7e0909949df"


def _event(body: dict, headers: dict | None = None) -> dict:
    return {
        "headers": headers if headers is not None else {"Authorization": "Bearer tok"},
        "body": json.dumps(body),
    }


def _patch_auth(monkeypatch):
    monkeypatch.setattr(
        "libs.utils.auth.UserBearerTokens",
        MagicMock(get_by_hash=MagicMock(return_value=MagicMock(revoked_at=None))),
    )
    monkeypatch.setattr("libs.utils.auth.is_alive", MagicMock(return_value=True))
    monkeypatch.setattr("libs.utils.auth.Users", MagicMock(get_by_id=MagicMock(return_value=MagicMock(id="u-1"))))


def _processes_response(processes, status_code=200):
    return {"statusCode": status_code, "body": json.dumps({"processes": processes})}


def _patch_lookup(h, monkeypatch, invoke):
    lookup = sys.modules[h.get_payable_process.__module__]
    monkeypatch.setattr(lookup, "invoke_sync", invoke)
    return invoke


def test_upload_url_happy_path(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    invoke = _patch_lookup(h, monkeypatch, MagicMock(return_value=_processes_response([{"id": _PID, "stage": "PAYMENT"}])))
    presign = MagicMock(return_value="https://s3.test/put")
    monkeypatch.setattr(h, "presign_upload", presign)

    resp = h.handler(_event({"process_id": _PID, "content_type": "image/png"}), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["upload_url"] == "https://s3.test/put"
    assert body["key"].startswith(f"payments/{_PID}/") and body["key"].endswith(".png")
    assert body["upload_headers"] == {"Content-Type": "image/png"}
    presign.assert_called_once_with(h.BUCKET, body["key"], "image/png")

    # The process check forwards the caller's Authorization header.
    assert invoke.call_args.kwargs == {
        "function_key": "get_processes",
        "payload": {"headers": {"Authorization": "Bearer tok"}},
        "service": "processes",
    }


def test_upload_url_never_uses_the_processes_prefix(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    _patch_lookup(h, monkeypatch, MagicMock(return_value=_processes_response([{"id": _PID, "stage": "PAYMENT"}])))
    monkeypatch.setattr(h, "presign_upload", MagicMock(return_value="u"))

    resp = h.handler(_event({"process_id": _PID}), None)

    key = json.loads(resp["body"])["key"]
    assert not key.startswith("processes/")
    assert key.endswith(".jpg")


def test_upload_url_invalid_process_id(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)

    resp = h.handler(_event({"process_id": "nope"}), None)

    assert resp["statusCode"] == 400


def test_upload_url_invalid_content_type(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)

    resp = h.handler(_event({"process_id": _PID, "content_type": "text/html"}), None)

    assert resp["statusCode"] == 400
    assert "content_type must be one of" in json.loads(resp["body"])["error"]


def test_upload_url_process_of_other_user_returns_404(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    _patch_lookup(h, monkeypatch, MagicMock(return_value=_processes_response([])))
    monkeypatch.setattr(h, "presign_upload", MagicMock(side_effect=AssertionError("must not presign")))

    resp = h.handler(_event({"process_id": _PID}), None)

    assert resp["statusCode"] == 404
    assert json.loads(resp["body"]) == {"error": "process_not_found"}


def test_upload_url_process_not_in_payment_returns_409(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    _patch_lookup(h, monkeypatch, MagicMock(return_value=_processes_response([{"id": _PID, "stage": "SIGNATURE"}])))
    monkeypatch.setattr(h, "presign_upload", MagicMock(side_effect=AssertionError("must not presign")))

    resp = h.handler(_event({"process_id": _PID}), None)

    assert resp["statusCode"] == 409
    assert json.loads(resp["body"]) == {"error": "process_not_in_payment_stage"}


def test_upload_url_processes_unreachable_returns_502(load_handler, monkeypatch):
    h = load_handler(__file__)
    _patch_auth(monkeypatch)
    _patch_lookup(h, monkeypatch, MagicMock(side_effect=LambdaInvokeError("fn", "boto_error", "timeout")))

    resp = h.handler(_event({"process_id": _PID}), None)

    assert resp["statusCode"] == 502
    assert json.loads(resp["body"]) == {"error": "processes_unavailable"}


def test_upload_url_requires_auth(load_handler):
    h = load_handler(__file__)

    resp = h.handler(_event({"process_id": _PID}, headers={}), None)

    assert resp["statusCode"] == 401
