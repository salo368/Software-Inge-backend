"""Cross-service Lambda-to-Lambda invocation helper.

Some flows need one Lambda to trigger another inside AWS without going
through API Gateway (e.g. `signatures.verify_otp` triggering the internal
`signatures.sign` Lambda asynchronously, or `signatures.sign` calling the
`mock_ca` helpers). This module wraps `boto3.client("lambda").invoke` with
the retries/timeouts we want everywhere and the naming convention this
repo already uses (`cdts-<stage>-<service>-<kebab-fn>`).

# (pipeline test: touching libs/ must trigger a transversal fan-out.)

Two invocation modes. Both take `function_key` (the snake_case folder name
of the target handler, e.g. `"simulate"`, `"sign"`) and resolve it to the
conventional Lambda name internally -- no separate naming step needed:

* `invoke_sync(function_key, payload=None, *, service=None) -> dict`
    Waits for the callee to finish, returns the parsed JSON payload it
    produced. Raises `LambdaInvokeError` if the callee returned a
    FunctionError, if the HTTP status was non-2xx, or if the response was
    not valid JSON.

* `invoke_async(function_key, payload=None, *, service=None) -> None`
    Fire-and-forget. Returns as soon as AWS accepts the invocation. Raises
    `LambdaInvokeError` only if the *submission* itself failed (StatusCode
    other than 202); the callee's outcome is not observed.

`service` defaults to the CALLER's own service (the `SERVICE` env var) when
omitted -- the common case of one handler invoking a sibling in the same
block. Pass it explicitly for a cross-service call, e.g.
`invoke_sync("simulate", event, service="banks")`.

Naming:

* `resolve_function_name(service, function_key, stage=None)` builds the
    conventional name `cdts-{stage}-{service}-{function_key_with_dashes}`.
    `service=None` falls back to `os.environ["SERVICE"]`; `stage` falls
    back to `os.environ["STAGE"]`. Exposed for callers that need the
    resolved name without invoking (e.g. for logging); `invoke_sync`/
    `invoke_async` call it internally, so most callers never need it.

IAM requirement:

The caller Lambda's role must include `lambda:InvokeFunction` on the target
Lambda's ARN. Callers must remember to widen their `serverless.yml` IAM
statements before wiring up an invocation.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from libs.core.logger import Logger


class LambdaInvokeError(Exception):
    """Raised when a cross-Lambda invocation fails.

    Attributes:
        function_name: The target Lambda that was invoked.
        error_type: Short machine-readable tag
            (`function_error`, `bad_status`, `bad_payload`, `boto_error`,
             `submission_failed`).
        detail: Human-readable description; safe to log, do not surface
            verbatim to end users.
    """

    def __init__(self, function_name: str, error_type: str, detail: str):
        super().__init__(f"{function_name}: {error_type}: {detail}")
        self.function_name = function_name
        self.error_type = error_type
        self.detail = detail


# ---------------------------------------------------------------------------
# Client (module-level, lazy). Kept lazy so importing this module does not
# open an AWS session in test environments that never actually invoke.
# Callers may monkeypatch `_get_client` to substitute a stub client.
# ---------------------------------------------------------------------------
_client = None


def _default_config(read_timeout_s: int = 30) -> BotoConfig:
    return BotoConfig(
        retries={"max_attempts": 2, "mode": "standard"},
        connect_timeout=5,
        read_timeout=read_timeout_s,
    )


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client("lambda", config=_default_config())
    return _client


def _reset_client_for_tests() -> None:
    """Test hook: forces the next call to rebuild the boto3 client."""
    global _client
    _client = None


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------
def resolve_function_name(
    service: Optional[str], function_key: str, stage: Optional[str] = None
) -> str:
    """Builds the conventional Lambda name for a handler in this repo.

    Matches `build-functions.js`: `cdts-{stage}-{service}-{folder-with-dashes}`.
    `function_key` is the snake_case folder name of the target handler; it
    is converted to kebab-case. `service=None` means "the caller's own
    service" and falls back to the `SERVICE` env var.

    Raises RuntimeError if `service`/`stage` were not passed and the
    matching env var is absent (defensive: silently defaulting would
    invoke the wrong Lambda or deploy to the wrong stage).
    """
    if not function_key:
        raise ValueError("function_key is required")
    resolved_service = service or os.environ.get("SERVICE")
    if not resolved_service:
        raise RuntimeError(
            "no service was passed and the SERVICE env var is not set; "
            "refusing to guess. Pass service=... explicitly for a "
            "cross-service call."
        )
    resolved_stage = stage or os.environ.get("STAGE")
    if not resolved_stage:
        raise RuntimeError(
            "STAGE env var is not set and no explicit stage was passed to "
            "resolve_function_name; refusing to guess."
        )
    fn_kebab = function_key.replace("_", "-")
    return f"cdts-{resolved_stage}-{resolved_service}-{fn_kebab}"


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------
def invoke_sync(function_key, payload = None, *, service = None) -> dict:
   
    function_name = resolve_function_name(service, function_key)
    body = json.dumps(payload or {}, default=str).encode("utf-8")
    Logger.log("INFO", f"invoke_sync -> {function_name} ({len(body)}B)")

    try:
        resp = _get_client().invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=body,
        )
    except (BotoCoreError, ClientError) as e:
        Logger.log("ERROR", f"invoke_sync boto error for {function_name}: {e}")
        raise LambdaInvokeError(function_name, "boto_error", str(e)) from e

    status = resp.get("StatusCode")
    if status != 200:
        raise LambdaInvokeError(
            function_name, "bad_status", f"StatusCode={status}"
        )

    fn_error = resp.get("FunctionError")
    raw = resp["Payload"].read()
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        raise LambdaInvokeError(
            function_name, "bad_payload", f"non-json response: {e}"
        ) from e

    if fn_error:
        detail = parsed.get("errorMessage") if isinstance(parsed, dict) else str(parsed)
        raise LambdaInvokeError(
            function_name, "function_error", f"{fn_error}: {detail}"
        )

    Logger.log("INFO", f"invoke_sync <- {function_name} ok")
    if not isinstance(parsed, dict):
        return {"result": parsed}
    return parsed


def invoke_async(
    function_key: str, payload: Optional[dict] = None, *, service: Optional[str] = None
) -> None:
    """Resolves `function_key` (defaulting `service` to the caller's own,
    see module docstring) and invokes it in fire-and-forget mode.

    Returns as soon as AWS accepts the invocation (StatusCode 202). Does
    not observe the callee's outcome; use CloudWatch or an explicit
    callback if the caller needs to know the result later.

    Raises `LambdaInvokeError` only if the submission itself failed.
    """
    function_name = resolve_function_name(service, function_key)
    body = json.dumps(payload or {}, default=str).encode("utf-8")
    Logger.log("INFO", f"invoke_async -> {function_name} ({len(body)}B)")

    try:
        resp = _get_client().invoke(
            FunctionName=function_name,
            InvocationType="Event",
            Payload=body,
        )
    except (BotoCoreError, ClientError) as e:
        Logger.log("ERROR", f"invoke_async boto error for {function_name}: {e}")
        raise LambdaInvokeError(function_name, "boto_error", str(e)) from e

    status = resp.get("StatusCode")
    # 202 is the documented success status for InvocationType=Event.
    if status != 202:
        raise LambdaInvokeError(
            function_name, "submission_failed", f"StatusCode={status}"
        )
