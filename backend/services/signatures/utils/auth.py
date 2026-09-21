"""Signature-service-local auth decorators.

Signatures uses two distinct auth models, neither of which fits the
bearer-token pattern from `libs.utils.auth`:

  * `require_service_key` -- for the M2M endpoint `POST /signatures`.
    The caller (another backend service, e.g. `processes`) sends the
    shared secret in the `X-Service-Key` header. The expected value
    lives in SSM under the path from `SSM_SIGNATURES_SERVICE_KEY` and
    is cached per warm container.

  * `require_sign_id` -- for every endpoint operated by the signer via
    the sign URL (`GET /signatures/{sign_id}` and everything
    downstream). The `sign_id` in the URL path IS the credential; it
    is a 32-byte urlsafe token with ~256 bits of entropy so guessing
    is infeasible. The decorator loads the `Signatures` row by
    `sign_id` and injects it into `event["signature"]`. Missing or
    unknown sign_ids get a uniform 404 (never 401) so an attacker
    cannot distinguish "no such ceremony" from "ceremony exists but
    you have no access" -- there is no such distinction here.
"""

from __future__ import annotations

import hmac
import os
from functools import wraps
from typing import Optional

import boto3

from libs.core.logger import Logger
from libs.core.responses import HandledError, generate_response
from libs.orm.signatures import Signatures


# ---------------------------------------------------------------------------
# Service key loading (lazy + cached at module scope for warm reuse)
# ---------------------------------------------------------------------------
_service_key_cache: Optional[str] = None


def _load_service_key() -> str:
    """Reads the M2M shared secret from SSM.

    Cached at module scope, so a warm Lambda re-uses it. On cold start
    this makes exactly one SSM call. Raises RuntimeError if the SSM
    path is not configured or the parameter is missing.
    """
    global _service_key_cache
    if _service_key_cache is not None:
        return _service_key_cache

    param_name = os.environ.get("SSM_SIGNATURES_SERVICE_KEY")
    if not param_name:
        raise RuntimeError("SSM_SIGNATURES_SERVICE_KEY env var is not set")
    try:
        resp = boto3.client("ssm").get_parameter(Name=param_name, WithDecryption=True)
    except Exception as e:
        raise RuntimeError(
            f"could not load signatures service-key from SSM ({param_name}): {e}"
        ) from e

    _service_key_cache = resp["Parameter"]["Value"]
    return _service_key_cache


def _reset_service_key_cache_for_tests() -> None:
    """Test hook: force the next `_load_service_key` call to re-fetch."""
    global _service_key_cache
    _service_key_cache = None


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------
def require_service_key(handler):
    """Rejects requests missing or mismatching the M2M `X-Service-Key`.

    Uses constant-time comparison to prevent timing attacks. Logs the
    rejection reason at WARNING level for operators; the client sees
    only a uniform 401.
    """

    @wraps(handler)
    def wrapper(event, context):
        headers = {
            k.lower(): v for k, v in (event.get("headers") or {}).items()
        }
        provided = headers.get("x-service-key", "").strip()
        if not provided:
            Logger.log("WARNING", "require_service_key: missing X-Service-Key header")
            return generate_response({"error": "missing_service_key"}, 401)

        try:
            expected = _load_service_key()
        except RuntimeError as e:
            # Operator misconfiguration; return 500 so the caller retries
            # or someone gets paged. Never leak the reason.
            Logger.log("ERROR", f"require_service_key: {e}")
            return generate_response({"error": "internal_server_error"}, 500)

        if not hmac.compare_digest(provided, expected):
            Logger.log("WARNING", "require_service_key: X-Service-Key mismatch")
            return generate_response({"error": "invalid_service_key"}, 401)

        return handler(event, context)

    return wrapper


def require_sign_id(handler):
    """Loads the Signatures row for `event.pathParameters.sign_id`.

    On success the row is at `event["signature"]`. On any failure the
    response is a uniform 404; distinguishing "no such sign_id",
    "expired", or "already terminal" would leak info to a scanner.
    Callers that need to react differently to expired/terminal states
    should check `event["signature"].stage` inside the handler.
    """

    @wraps(handler)
    def wrapper(event, context):
        sign_id = (event.get("pathParameters") or {}).get("sign_id", "").strip()
        if not sign_id:
            Logger.log("WARNING", "require_sign_id: no sign_id in path")
            return generate_response({"error": "signature_not_found"}, 404)

        row = Signatures.get_by_sign_id(sign_id)
        if row is None:
            Logger.log("WARNING", f"require_sign_id: no row for {sign_id[:6]}...")
            return generate_response({"error": "signature_not_found"}, 404)

        event["signature"] = row
        return handler(event, context)

    return wrapper


# ---------------------------------------------------------------------------
# Stage gating helpers
# ---------------------------------------------------------------------------
def ensure_stage_allows(signature, allowed: tuple[str, ...]) -> None:
    """Raises HandledError(409) if the signature is not in an allowed stage.

    Terminal states (`signed`, `expired`, `failed`) never allow further
    action; even if they are in `allowed` this returns 410 Gone so the
    caller distinguishes "ceremony finished" from generic stage guard
    violations.
    """
    if signature.stage in ("signed", "expired", "failed"):
        raise HandledError(f"ceremony_{signature.stage}", 410)
    if signature.stage not in allowed:
        raise HandledError(
            f"stage_not_allowed_current_{signature.stage}", 409
        )
