"""Unit tests for `libs.utils.lambda_invoke`.

Cross-cutting util (not colocated with any handler), so lives under
`backend/tests/` and uses direct imports instead of the `load_handler`
fixture. The boto3 client is monkeypatched through `_get_client` so no
real AWS call happens.
"""
from __future__ import annotations

import io
import json
from unittest.mock import MagicMock

import pytest

from libs.utils import lambda_invoke as li


# ---------------------------------------------------------------------------
# resolve_function_name
# ---------------------------------------------------------------------------
class TestResolveFunctionName:
    def test_builds_name_from_stage_env(self, monkeypatch):
        monkeypatch.setenv("STAGE", "dev")
        name = li.resolve_function_name("signatures", "sign")
        assert name == "cdts-dev-signatures-sign"

    def test_snake_case_folder_becomes_kebab(self, monkeypatch):
        monkeypatch.setenv("STAGE", "pro")
        # matches `build-functions.js`: folder "verify_otp" -> "verify-otp"
        name = li.resolve_function_name("signatures", "verify_otp")
        assert name == "cdts-pro-signatures-verify-otp"

    def test_explicit_stage_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("STAGE", "dev")
        assert (
            li.resolve_function_name("processes", "create", stage="pro")
            == "cdts-pro-processes-create"
        )

    def test_raises_when_no_stage_available(self, monkeypatch):
        monkeypatch.delenv("STAGE", raising=False)
        with pytest.raises(RuntimeError, match="STAGE env var"):
            li.resolve_function_name("signatures", "sign")

    def test_rejects_empty_arguments(self, monkeypatch):
        monkeypatch.setenv("STAGE", "dev")
        with pytest.raises(ValueError):
            li.resolve_function_name("", "sign")
        with pytest.raises(ValueError):
            li.resolve_function_name("signatures", "")


# ---------------------------------------------------------------------------
# invoke_sync
# ---------------------------------------------------------------------------
def _payload_stream(obj) -> io.BytesIO:
    """boto3's real Payload is a StreamingBody; only .read() is used."""
    return io.BytesIO(json.dumps(obj).encode("utf-8"))


class TestInvokeSync:
    def setup_method(self):
        li._reset_client_for_tests()

    def test_happy_path_returns_parsed_payload(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.invoke.return_value = {
            "StatusCode": 200,
            "Payload": _payload_stream({"ok": True, "sign_id": "abc"}),
        }
        monkeypatch.setattr(li, "_get_client", lambda: fake_client)

        result = li.invoke_sync("cdts-dev-signatures-sign", {"sign_id": "abc"})

        assert result == {"ok": True, "sign_id": "abc"}
        # Payload sent to boto3 is JSON-encoded bytes.
        _, kwargs = fake_client.invoke.call_args
        assert kwargs["FunctionName"] == "cdts-dev-signatures-sign"
        assert kwargs["InvocationType"] == "RequestResponse"
        assert json.loads(kwargs["Payload"]) == {"sign_id": "abc"}

    def test_none_payload_becomes_empty_object(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.invoke.return_value = {
            "StatusCode": 200,
            "Payload": _payload_stream({}),
        }
        monkeypatch.setattr(li, "_get_client", lambda: fake_client)

        li.invoke_sync("cdts-dev-x-y")

        _, kwargs = fake_client.invoke.call_args
        assert json.loads(kwargs["Payload"]) == {}

    def test_function_error_raises(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.invoke.return_value = {
            "StatusCode": 200,
            "FunctionError": "Unhandled",
            "Payload": _payload_stream(
                {"errorType": "ValueError", "errorMessage": "boom"}
            ),
        }
        monkeypatch.setattr(li, "_get_client", lambda: fake_client)

        with pytest.raises(li.LambdaInvokeError) as exc:
            li.invoke_sync("cdts-dev-signatures-sign", {})

        assert exc.value.error_type == "function_error"
        assert "boom" in exc.value.detail

    def test_non_200_status_raises(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.invoke.return_value = {
            "StatusCode": 429,
            "Payload": _payload_stream({}),
        }
        monkeypatch.setattr(li, "_get_client", lambda: fake_client)

        with pytest.raises(li.LambdaInvokeError) as exc:
            li.invoke_sync("cdts-dev-signatures-sign", {})

        assert exc.value.error_type == "bad_status"
        assert "429" in exc.value.detail

    def test_non_json_payload_raises(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.invoke.return_value = {
            "StatusCode": 200,
            "Payload": io.BytesIO(b"<html>oops</html>"),
        }
        monkeypatch.setattr(li, "_get_client", lambda: fake_client)

        with pytest.raises(li.LambdaInvokeError) as exc:
            li.invoke_sync("cdts-dev-signatures-sign", {})

        assert exc.value.error_type == "bad_payload"

    def test_empty_payload_returns_empty_dict(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.invoke.return_value = {
            "StatusCode": 200,
            "Payload": io.BytesIO(b""),
        }
        monkeypatch.setattr(li, "_get_client", lambda: fake_client)

        assert li.invoke_sync("cdts-dev-x-y") == {}

    def test_non_dict_payload_wrapped(self, monkeypatch):
        """A callee that returns a JSON array is unusual but shouldn't crash
        the caller silently; wrap it under `result` so the return type
        matches the annotation."""
        fake_client = MagicMock()
        fake_client.invoke.return_value = {
            "StatusCode": 200,
            "Payload": _payload_stream([1, 2, 3]),
        }
        monkeypatch.setattr(li, "_get_client", lambda: fake_client)

        assert li.invoke_sync("cdts-dev-x-y") == {"result": [1, 2, 3]}

    def test_boto_client_error_translated(self, monkeypatch):
        from botocore.exceptions import ClientError

        fake_client = MagicMock()
        fake_client.invoke.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "nope"}},
            "Invoke",
        )
        monkeypatch.setattr(li, "_get_client", lambda: fake_client)

        with pytest.raises(li.LambdaInvokeError) as exc:
            li.invoke_sync("cdts-dev-signatures-sign", {})

        assert exc.value.error_type == "boto_error"
        assert exc.value.function_name == "cdts-dev-signatures-sign"


# ---------------------------------------------------------------------------
# invoke_async
# ---------------------------------------------------------------------------
class TestInvokeAsync:
    def setup_method(self):
        li._reset_client_for_tests()

    def test_happy_path_returns_none(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.invoke.return_value = {"StatusCode": 202}
        monkeypatch.setattr(li, "_get_client", lambda: fake_client)

        assert li.invoke_async("cdts-dev-signatures-sign", {"sign_id": "x"}) is None

        _, kwargs = fake_client.invoke.call_args
        assert kwargs["InvocationType"] == "Event"
        assert json.loads(kwargs["Payload"]) == {"sign_id": "x"}

    def test_non_202_raises_submission_failed(self, monkeypatch):
        fake_client = MagicMock()
        fake_client.invoke.return_value = {"StatusCode": 500}
        monkeypatch.setattr(li, "_get_client", lambda: fake_client)

        with pytest.raises(li.LambdaInvokeError) as exc:
            li.invoke_async("cdts-dev-signatures-sign", {})

        assert exc.value.error_type == "submission_failed"

    def test_boto_error_translated(self, monkeypatch):
        from botocore.exceptions import BotoCoreError

        fake_client = MagicMock()
        fake_client.invoke.side_effect = BotoCoreError()
        monkeypatch.setattr(li, "_get_client", lambda: fake_client)

        with pytest.raises(li.LambdaInvokeError) as exc:
            li.invoke_async("cdts-dev-signatures-sign", {})

        assert exc.value.error_type == "boto_error"
