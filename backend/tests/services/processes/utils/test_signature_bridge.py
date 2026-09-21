"""Unit tests for `services/processes/utils/signature_bridge.py`.

Cross-cutting because the module lives inside processes' block-local
utils/ but has no `handler.py` sibling. Same sys.path escape hatch as
`test_investment_order.py`.

The bridge is a data-shuffling function with 3 side effects:
    * S3 put on the files bucket
    * S3 presign for a GET URL
    * Lambda invoke to signatures.create

All three are stubbed; we only assert that the arguments handed over
match what the signatures API contract expects. The actual PDF
rendering is exercised by `test_investment_order.py`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

# We need to import both `utils.signature_bridge` AND its dependency
# `utils.investment_order` -- the former imports the latter via the
# namespace package. Point sys.path at `services/processes/` (parent of
# utils/) so the `utils.*` package resolves as it does inside the
# production Lambda's package layout.
_BACKEND = Path(__file__).resolve().parents[4]
_PROC_ROOT = _BACKEND / "services" / "processes"
sys.path.insert(0, str(_PROC_ROOT))

# Purge any prior `utils` binding another test's `load_handler` might
# have parked in sys.modules; otherwise Python could resolve modules
# below against a stale namespace pointing at a different service.
for _n in list(sys.modules):
    if _n == "utils" or _n.startswith("utils."):
        sys.modules.pop(_n, None)

# Ensure the env vars the module reads at import time are set. The root
# conftest already primes FILES_BUCKET and SSM_SIGNATURES_SERVICE_KEY;
# add them defensively so this module can also run in isolation.
import os

os.environ.setdefault("FILES_BUCKET", "cdts-test-files")
os.environ.setdefault(
    "SSM_SIGNATURES_SERVICE_KEY", "/cdts/test/signatures/service-key"
)
os.environ.setdefault("STAGE", "test")

from utils import signature_bridge  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_cache():
    signature_bridge._reset_service_key_cache_for_tests()
    signature_bridge._reset_callback_url_cache_for_tests()
    yield
    signature_bridge._reset_service_key_cache_for_tests()
    signature_bridge._reset_callback_url_cache_for_tests()


def _stub_ssm(monkeypatch, *, service_key="s3cr3t"):
    ssm = MagicMock()
    ssm.get_parameter.return_value = {"Parameter": {"Value": service_key}}
    # boto3.client is called twice in this module (ssm + s3). We
    # dispatch on the service name via a factory.
    def _factory(service_name, *args, **kwargs):
        if service_name == "ssm":
            return ssm
        raise AssertionError(f"unexpected boto3.client call for {service_name!r}")
    return ssm, _factory


def _stub_s3(monkeypatch, *, put_raises=None, presign_url="https://s3.test/x"):
    s3 = MagicMock()
    if put_raises is not None:
        s3.put_object = MagicMock(side_effect=put_raises)
    else:
        s3.put_object = MagicMock()
    s3.generate_presigned_url = MagicMock(return_value=presign_url)
    return s3


def _wire(
    monkeypatch,
    *,
    invoke_return: dict | None = None,
    invoke_raises: Exception | None = None,
    s3_put_raises: Exception | None = None,
    presign_url: str = "https://s3.test/x?sig=abc",
    service_key: str = "s3cr3t",
    api_url_base: str | None = "https://api.test",
    api_url_raises: Exception | None = None,
    ssm_processes_api_url_env: str | None = "/cdts/test/processes-api/url",
):
    ssm = MagicMock()

    # SSM.get_parameter is called for two DIFFERENT params depending on
    # what the bridge needs: the service key and (optionally) the
    # processes API URL. Dispatch by Name so tests can control each
    # independently.
    def _get_parameter(Name, WithDecryption=False, **_):  # noqa: N803
        if Name == "/cdts/test/signatures/service-key":
            return {"Parameter": {"Value": service_key}}
        if Name == "/cdts/test/processes-api/url":
            if api_url_raises is not None:
                raise api_url_raises
            if api_url_base is None:
                raise KeyError("api url not primed")
            return {"Parameter": {"Value": api_url_base}}
        raise AssertionError(f"unexpected ssm.get_parameter call: {Name!r}")

    ssm.get_parameter.side_effect = _get_parameter

    # Toggle whether the bridge module SEES the processes API URL env
    # var. Setting to None simulates "not configured at deploy time".
    if ssm_processes_api_url_env is None:
        monkeypatch.setattr(signature_bridge, "SSM_PROCESSES_API_URL", "")
    else:
        monkeypatch.setattr(
            signature_bridge, "SSM_PROCESSES_API_URL", ssm_processes_api_url_env
        )

    s3 = _stub_s3(monkeypatch, put_raises=s3_put_raises, presign_url=presign_url)

    def _boto3_client(service_name, *args, **kwargs):
        return {"ssm": ssm, "s3": s3}[service_name]

    monkeypatch.setattr(signature_bridge.boto3, "client", _boto3_client)

    # PDF renderer: we don't care about bytes here, just that they're
    # forwarded. Return a small non-empty PDF-shaped payload.
    monkeypatch.setattr(
        signature_bridge,
        "build_investment_order",
        MagicMock(return_value=b"%PDF-1.7\nfake\n%%EOF"),
    )

    invoke = MagicMock()
    if invoke_raises is not None:
        invoke.side_effect = invoke_raises
    else:
        invoke.return_value = invoke_return
    monkeypatch.setattr(signature_bridge, "invoke_sync", invoke)

    return {"ssm": ssm, "s3": s3, "invoke": invoke}


def _stock_signatures_response(sign_id="sign_abc", sign_url="https://front.test/sign/sign_abc"):
    """Envelope shape produced by signatures.create (API Gateway
    HTTP-response style)."""
    return {
        "statusCode": 201,
        "body": json.dumps(
            {
                "sign_id": sign_id,
                "sign_url": sign_url,
                "hash_original": "a" * 64,
                "expires_at": "2026-09-22T00:00:00+00:00",
            }
        ),
    }


def _fake_process(**overrides):
    from decimal import Decimal

    defaults = {
        "id": uuid4(),
        "amount": Decimal("5000000"),
        "rate": Decimal("12.5"),
        "term_days": 180,
        "form_snapshot": {"full_name": "Ada"},
    }
    defaults.update(overrides)
    return SimpleNamespace(sign_id=None, **defaults)


def _fake_user(**overrides):
    defaults = {"email": "titular@example.com", "full_name": "Ada Lovelace"}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _fake_bank(**overrides):
    defaults = {"name": "Banco Popular"}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------
class TestPreconditions:
    def test_missing_user_email_raises(self, monkeypatch):
        _wire(monkeypatch, invoke_return=_stock_signatures_response())
        with pytest.raises(signature_bridge.SignatureBridgeError) as exc:
            signature_bridge.open_ceremony_for_process(
                proc=_fake_process(),
                user=SimpleNamespace(email=None, full_name="Ada"),
                bank=_fake_bank(),
            )
        assert exc.value.code == "user_missing_email"

    def test_missing_bank_raises(self, monkeypatch):
        _wire(monkeypatch, invoke_return=_stock_signatures_response())
        with pytest.raises(signature_bridge.SignatureBridgeError) as exc:
            signature_bridge.open_ceremony_for_process(
                proc=_fake_process(),
                user=_fake_user(),
                bank=None,
            )
        assert exc.value.code == "bank_not_found"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
class TestHappyPath:
    def test_returns_sign_url_and_binds_sign_id(self, monkeypatch):
        stubs = _wire(monkeypatch, invoke_return=_stock_signatures_response())
        proc = _fake_process()
        url = signature_bridge.open_ceremony_for_process(
            proc=proc, user=_fake_user(), bank=_fake_bank()
        )
        assert url == "https://front.test/sign/sign_abc"
        assert proc.sign_id == "sign_abc"

    def test_uploads_pdf_under_expected_key(self, monkeypatch):
        stubs = _wire(monkeypatch, invoke_return=_stock_signatures_response())
        proc = _fake_process()
        signature_bridge.open_ceremony_for_process(
            proc=proc, user=_fake_user(), bank=_fake_bank()
        )
        stubs["s3"].put_object.assert_called_once()
        _, kw = stubs["s3"].put_object.call_args
        assert kw["Bucket"] == "cdts-test-files"
        assert kw["Key"] == f"processes/{proc.id}/investment-order.pdf"
        assert kw["ContentType"] == "application/pdf"
        assert kw["Body"].startswith(b"%PDF")

    def test_presigns_get_url_on_uploaded_key(self, monkeypatch):
        stubs = _wire(monkeypatch, invoke_return=_stock_signatures_response())
        proc = _fake_process()
        signature_bridge.open_ceremony_for_process(
            proc=proc, user=_fake_user(), bank=_fake_bank()
        )
        stubs["s3"].generate_presigned_url.assert_called_once()
        args, kw = stubs["s3"].generate_presigned_url.call_args
        assert args[0] == "get_object"
        assert kw["Params"]["Bucket"] == "cdts-test-files"
        assert kw["Params"]["Key"] == f"processes/{proc.id}/investment-order.pdf"
        # TTL is short by design (< 15 min).
        assert 60 <= kw["ExpiresIn"] <= 900

    def test_invokes_signatures_create_with_expected_payload(self, monkeypatch):
        stubs = _wire(
            monkeypatch,
            invoke_return=_stock_signatures_response(),
            presign_url="https://s3.test/pdf?sig=xyz",
        )
        proc = _fake_process()
        signature_bridge.open_ceremony_for_process(
            proc=proc,
            user=_fake_user(email="Ada@Example.com", full_name="Ada Lovelace"),
            bank=_fake_bank(name="Banco Popular"),
        )

        stubs["invoke"].assert_called_once()
        args, kw = stubs["invoke"].call_args
        target_fn = args[0]
        assert target_fn == "cdts-test-signatures-create"

        payload = args[1]
        headers = payload["headers"]
        assert headers["X-Service-Key"] == "s3cr3t"

        body = json.loads(payload["body"])
        assert body["pdf_source_url"] == "https://s3.test/pdf?sig=xyz"
        assert body["signer_email"] == "Ada@Example.com"
        assert body["signer_name"] == "Ada Lovelace"
        assert body["service_caller"] == "processes"
        # SIGNATURE_LOCATION comes from investment_order.py; verify it's
        # a dict shaped like the signatures contract.
        loc = body["signature_location"]
        for k in ("page", "x_pct", "y_pct", "width_pct"):
            assert k in loc

    def test_service_key_is_cached_across_calls(self, monkeypatch):
        stubs = _wire(monkeypatch, invoke_return=_stock_signatures_response())
        signature_bridge.open_ceremony_for_process(
            proc=_fake_process(), user=_fake_user(), bank=_fake_bank()
        )
        signature_bridge.open_ceremony_for_process(
            proc=_fake_process(), user=_fake_user(), bank=_fake_bank()
        )
        # Two SSM roundtrips per warm container across an unlimited
        # number of ceremonies: one for the service key, one for the
        # processes API URL. Both cached at module scope.
        assert stubs["ssm"].get_parameter.call_count == 2


# ---------------------------------------------------------------------------
# callback_url discovery (fase 6b wiring)
# ---------------------------------------------------------------------------
class TestCallbackUrl:
    def test_callback_url_built_from_ssm_base(self, monkeypatch):
        stubs = _wire(
            monkeypatch,
            invoke_return=_stock_signatures_response(),
            api_url_base="https://api.dev.example.com",
        )
        signature_bridge.open_ceremony_for_process(
            proc=_fake_process(), user=_fake_user(), bank=_fake_bank()
        )
        args, _ = stubs["invoke"].call_args
        body = json.loads(args[1]["body"])
        assert (
            body["callback_url"]
            == "https://api.dev.example.com/processes/signature-callback"
        )

    def test_trailing_slash_on_base_is_stripped(self, monkeypatch):
        stubs = _wire(
            monkeypatch,
            invoke_return=_stock_signatures_response(),
            api_url_base="https://api.dev.example.com/",
        )
        signature_bridge.open_ceremony_for_process(
            proc=_fake_process(), user=_fake_user(), bank=_fake_bank()
        )
        args, _ = stubs["invoke"].call_args
        body = json.loads(args[1]["body"])
        assert (
            body["callback_url"]
            == "https://api.dev.example.com/processes/signature-callback"
        )

    def test_env_unset_means_null_callback(self, monkeypatch):
        """First-ever deploy before the ProcessesApiUrlParam resource
        has been created: SSM_PROCESSES_API_URL env is empty. Ceremony
        still opens; frontend has to poll."""
        stubs = _wire(
            monkeypatch,
            invoke_return=_stock_signatures_response(),
            ssm_processes_api_url_env=None,
        )
        signature_bridge.open_ceremony_for_process(
            proc=_fake_process(), user=_fake_user(), bank=_fake_bank()
        )
        args, _ = stubs["invoke"].call_args
        body = json.loads(args[1]["body"])
        assert body["callback_url"] is None

    def test_ssm_lookup_failure_means_null_callback(self, monkeypatch):
        """SSM param path is configured but the param doesn't exist yet
        (or IAM missed a permission). We don't raise -- opening
        ceremonies is more important than getting the webhook."""
        stubs = _wire(
            monkeypatch,
            invoke_return=_stock_signatures_response(),
            api_url_raises=RuntimeError("ParameterNotFound"),
        )
        signature_bridge.open_ceremony_for_process(
            proc=_fake_process(), user=_fake_user(), bank=_fake_bank()
        )
        args, _ = stubs["invoke"].call_args
        body = json.loads(args[1]["body"])
        assert body["callback_url"] is None

    def test_callback_url_is_cached(self, monkeypatch):
        """Both the successful lookup AND the "not configured" outcome
        are cached, so a warm container hits SSM at most once per
        param across its lifetime."""
        stubs = _wire(
            monkeypatch,
            invoke_return=_stock_signatures_response(),
            api_url_base="https://api.dev.example.com",
        )
        signature_bridge.open_ceremony_for_process(
            proc=_fake_process(), user=_fake_user(), bank=_fake_bank()
        )
        signature_bridge.open_ceremony_for_process(
            proc=_fake_process(), user=_fake_user(), bank=_fake_bank()
        )
        # Same total (2) as when opening a single ceremony -- neither
        # the service key nor the API URL was re-fetched.
        assert stubs["ssm"].get_parameter.call_count == 2


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------
class TestFailures:
    def test_ssm_failure_maps_to_service_key_unavailable(self, monkeypatch):
        stubs = _wire(monkeypatch, invoke_return=_stock_signatures_response())
        stubs["ssm"].get_parameter.side_effect = RuntimeError("ssm boom")
        with pytest.raises(signature_bridge.SignatureBridgeError) as exc:
            signature_bridge.open_ceremony_for_process(
                proc=_fake_process(), user=_fake_user(), bank=_fake_bank()
            )
        assert exc.value.code == "service_key_unavailable"

    def test_s3_upload_failure_maps_to_stable_code(self, monkeypatch):
        _wire(
            monkeypatch,
            invoke_return=_stock_signatures_response(),
            s3_put_raises=RuntimeError("s3 boom"),
        )
        with pytest.raises(signature_bridge.SignatureBridgeError) as exc:
            signature_bridge.open_ceremony_for_process(
                proc=_fake_process(), user=_fake_user(), bank=_fake_bank()
            )
        assert exc.value.code == "s3_upload_failed"

    def test_invoke_failure_maps_to_signatures_invoke_failed(self, monkeypatch):
        from libs.utils.lambda_invoke import LambdaInvokeError

        _wire(
            monkeypatch,
            invoke_raises=LambdaInvokeError(
                "cdts-test-signatures-create", "boto_error", "throttled"
            ),
        )
        with pytest.raises(signature_bridge.SignatureBridgeError) as exc:
            signature_bridge.open_ceremony_for_process(
                proc=_fake_process(), user=_fake_user(), bank=_fake_bank()
            )
        assert exc.value.code == "signatures_invoke_failed"

    def test_non_201_response_maps_to_signatures_create_rejected(self, monkeypatch):
        _wire(
            monkeypatch,
            invoke_return={
                "statusCode": 400,
                "body": json.dumps({"error": "invalid_pdf_source_url"}),
            },
        )
        with pytest.raises(signature_bridge.SignatureBridgeError) as exc:
            signature_bridge.open_ceremony_for_process(
                proc=_fake_process(), user=_fake_user(), bank=_fake_bank()
            )
        assert exc.value.code == "signatures_create_rejected"
        # The upstream error should surface in the detail for operators.
        assert "invalid_pdf_source_url" in exc.value.detail

    def test_missing_sign_id_in_response_maps_to_missing_field(self, monkeypatch):
        _wire(
            monkeypatch,
            invoke_return={
                "statusCode": 201,
                "body": json.dumps({"sign_url": "https://x", "hash_original": "..."}),
            },
        )
        with pytest.raises(signature_bridge.SignatureBridgeError) as exc:
            signature_bridge.open_ceremony_for_process(
                proc=_fake_process(), user=_fake_user(), bank=_fake_bank()
            )
        assert exc.value.code == "signatures_missing_field"
        assert "sign_id" in exc.value.detail

    def test_missing_sign_url_in_response_maps_to_missing_field(self, monkeypatch):
        _wire(
            monkeypatch,
            invoke_return={
                "statusCode": 201,
                "body": json.dumps({"sign_id": "sign_abc"}),
            },
        )
        with pytest.raises(signature_bridge.SignatureBridgeError) as exc:
            signature_bridge.open_ceremony_for_process(
                proc=_fake_process(), user=_fake_user(), bank=_fake_bank()
            )
        assert exc.value.code == "signatures_missing_field"
