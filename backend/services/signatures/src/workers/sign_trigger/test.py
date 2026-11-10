"""Unit tests for the signatures sign_trigger worker."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4


def test_sign_trigger_posts_payload_to_webhook(load_handler, monkeypatch):
    h = load_handler(__file__)

    monkeypatch.setattr(h, "SSM_SIGN_TRIGGER_PATH", "/cdts/test/signatures/sign-trigger-webhook")
    monkeypatch.setattr(h, "_webhook_url_loaded", False)
    ssm_mock = MagicMock()
    ssm_mock.get_parameter.return_value = {"Parameter": {"Value": "https://example.com/hook"}}
    monkeypatch.setattr(h.boto3, "client", MagicMock(return_value=ssm_mock))

    resp_mock = MagicMock(status_code=200)
    post_mock = MagicMock(return_value=resp_mock)
    monkeypatch.setattr(h.requests, "post", post_mock)

    sig_id = uuid4()
    result = h.handler({"signature_id": str(sig_id), "stage": "SIGNED"}, None)

    assert result == {"ok": True, "signature_id": str(sig_id), "stage": "SIGNED"}
    url, kwargs = post_mock.call_args.args[0], post_mock.call_args.kwargs
    assert url == "https://example.com/hook"
    assert kwargs["json"] == {"signature_id": str(sig_id), "stage": "SIGNED"}


def test_sign_trigger_caches_webhook_url_across_calls(load_handler, monkeypatch):
    h = load_handler(__file__)

    monkeypatch.setattr(h, "SSM_SIGN_TRIGGER_PATH", "/cdts/test/signatures/sign-trigger-webhook")
    monkeypatch.setattr(h, "_webhook_url_loaded", False)
    ssm_mock = MagicMock()
    ssm_mock.get_parameter.return_value = {"Parameter": {"Value": "https://example.com/hook"}}
    monkeypatch.setattr(h.boto3, "client", MagicMock(return_value=ssm_mock))
    monkeypatch.setattr(h.requests, "post", MagicMock(return_value=MagicMock(status_code=200)))

    h.handler({"signature_id": str(uuid4()), "stage": "SIGNED"}, None)
    h.handler({"signature_id": str(uuid4()), "stage": "FAILED"}, None)

    ssm_mock.get_parameter.assert_called_once()


def test_sign_trigger_no_webhook_configured_is_skipped(load_handler, monkeypatch):
    h = load_handler(__file__)

    monkeypatch.setattr(h, "SSM_SIGN_TRIGGER_PATH", None)
    monkeypatch.setattr(h, "_webhook_url_loaded", False)
    monkeypatch.setattr(h.requests, "post", MagicMock(side_effect=AssertionError))

    result = h.handler({"signature_id": str(uuid4()), "stage": "SIGNED"}, None)

    assert result == {"ok": False, "skipped": True}


def test_sign_trigger_ssm_param_missing_is_skipped(load_handler, monkeypatch):
    h = load_handler(__file__)

    monkeypatch.setattr(h, "SSM_SIGN_TRIGGER_PATH", "/cdts/test/signatures/sign-trigger-webhook")
    monkeypatch.setattr(h, "_webhook_url_loaded", False)
    ssm_mock = MagicMock()
    ssm_mock.get_parameter.side_effect = Exception("ParameterNotFound")
    monkeypatch.setattr(h.boto3, "client", MagicMock(return_value=ssm_mock))
    monkeypatch.setattr(h.requests, "post", MagicMock(side_effect=AssertionError))

    result = h.handler({"signature_id": str(uuid4()), "stage": "SIGNED"}, None)

    assert result == {"ok": False, "skipped": True}


def test_sign_trigger_webhook_unreachable(load_handler, monkeypatch):
    h = load_handler(__file__)

    monkeypatch.setattr(h, "SSM_SIGN_TRIGGER_PATH", "/cdts/test/signatures/sign-trigger-webhook")
    monkeypatch.setattr(h, "_webhook_url_loaded", False)
    ssm_mock = MagicMock()
    ssm_mock.get_parameter.return_value = {"Parameter": {"Value": "https://example.com/hook"}}
    monkeypatch.setattr(h.boto3, "client", MagicMock(return_value=ssm_mock))
    monkeypatch.setattr(h.requests, "post", MagicMock(side_effect=h.requests.RequestException("timeout")))

    result = h.handler({"signature_id": str(uuid4()), "stage": "SIGNED"}, None)

    assert result == {"ok": False, "error": "webhook_unreachable"}


def test_sign_trigger_webhook_error_status(load_handler, monkeypatch):
    h = load_handler(__file__)

    monkeypatch.setattr(h, "SSM_SIGN_TRIGGER_PATH", "/cdts/test/signatures/sign-trigger-webhook")
    monkeypatch.setattr(h, "_webhook_url_loaded", False)
    ssm_mock = MagicMock()
    ssm_mock.get_parameter.return_value = {"Parameter": {"Value": "https://example.com/hook"}}
    monkeypatch.setattr(h.boto3, "client", MagicMock(return_value=ssm_mock))
    monkeypatch.setattr(h.requests, "post", MagicMock(return_value=MagicMock(status_code=500)))

    result = h.handler({"signature_id": str(uuid4()), "stage": "SIGNED"}, None)

    assert result == {"ok": False, "error": "webhook_status_500"}


def test_sign_trigger_bad_payload(load_handler, monkeypatch):
    h = load_handler(__file__)
    monkeypatch.setattr(h.requests, "post", MagicMock(side_effect=AssertionError))

    result = h.handler({"signature_id": str(uuid4()), "stage": "BOGUS"}, None)

    assert result == {"ok": False, "error": "bad_payload"}
