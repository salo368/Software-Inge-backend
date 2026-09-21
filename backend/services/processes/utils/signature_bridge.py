"""Pegamento entre `processes` y el servicio genérico `signatures`.

Signatures no sabe nada de CDTs, procesos, bancos ni formularios. Este
módulo es donde `processes` traduce lo suyo (proceso + usuario + banco
+ form snapshot) al contrato genérico de `signatures.create`.

Flujo de `open_ceremony_for_process`:

    1. Renderiza el PDF de la orden con `investment_order.build_investment_order`.
    2. Sube el PDF al bucket `files` bajo
       `processes/{process_id}/investment-order.pdf`.
    3. Genera una presigned GET URL de 10 min contra ese objeto.
    4. Invoca `signatures.create` vía `lambda:Invoke` (RequestResponse),
       pasando el X-Service-Key desde SSM. NO viaja por API Gateway ni
       expone el key al mundo.
    5. Guarda `sign_id` retornado en `proc.sign_id` (lo persiste el
       caller vía la sesión ya abierta; no hacemos flush explícito
       aquí).
    6. Devuelve el `sign_url` para que el caller lo mande al frontend.

Errores modelados como `SignatureBridgeError` (código estable +
detalle). El caller (advance) los mapea a HandledError(s) 4xx/5xx.
"""

from __future__ import annotations

import json
import os
from typing import Optional
from uuid import UUID

import boto3

from libs.core.logger import Logger
from libs.utils.lambda_invoke import (
    LambdaInvokeError,
    invoke_sync,
    resolve_function_name,
)

from utils.investment_order import SIGNATURE_LOCATION, build_investment_order


FILES_BUCKET = os.environ["FILES_BUCKET"]
SSM_SIGNATURES_SERVICE_KEY = os.environ["SSM_SIGNATURES_SERVICE_KEY"]

# Presigned GET URL TTL. Signatures.create downloads the PDF within
# seconds of receiving the URL; 10 minutes covers cold starts + retries
# without leaving a long-lived leak.
_PRESIGNED_TTL_S = 600


class SignatureBridgeError(Exception):
    """Stable codes for the bridge steps."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------
# SSM cache -- the service key is invariant per stage, so read once per warm
# container. Same pattern as signatures/utils/auth.py.
# ---------------------------------------------------------------------------
_service_key_cache: Optional[str] = None


def _load_service_key() -> str:
    global _service_key_cache
    if _service_key_cache is not None:
        return _service_key_cache
    try:
        resp = boto3.client("ssm").get_parameter(
            Name=SSM_SIGNATURES_SERVICE_KEY, WithDecryption=True
        )
    except Exception as e:
        raise SignatureBridgeError(
            "service_key_unavailable",
            f"could not load {SSM_SIGNATURES_SERVICE_KEY}: {e}",
        ) from e
    _service_key_cache = resp["Parameter"]["Value"]
    return _service_key_cache


def _reset_service_key_cache_for_tests() -> None:
    """Test hook: forces the next `_load_service_key` call to re-fetch."""
    global _service_key_cache
    _service_key_cache = None


# ---------------------------------------------------------------------------
# S3 helpers (files bucket)
# ---------------------------------------------------------------------------
def _s3():
    return boto3.client("s3")


def _upload_pdf(process_id: UUID, pdf_bytes: bytes) -> str:
    """Uploads the rendered PDF under a per-process prefix. Overwrites
    any prior copy so re-triggering `advance` (idempotence for retries)
    doesn't leave stale objects behind. Returns the S3 key."""
    key = f"processes/{process_id}/investment-order.pdf"
    try:
        _s3().put_object(
            Bucket=FILES_BUCKET,
            Key=key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
    except Exception as e:
        raise SignatureBridgeError("s3_upload_failed", str(e)) from e
    return key


def _presign_get(key: str) -> str:
    try:
        return _s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": FILES_BUCKET, "Key": key},
            ExpiresIn=_PRESIGNED_TTL_S,
        )
    except Exception as e:
        raise SignatureBridgeError("presign_failed", str(e)) from e


# ---------------------------------------------------------------------------
# Cross-service call to signatures.create
# ---------------------------------------------------------------------------
def _invoke_signatures_create(
    *,
    pdf_source_url: str,
    signer_email: str,
    signer_name: str,
    process_id: UUID,
) -> dict:
    """Calls `signatures.create` via direct Lambda invoke. Bypasses API
    Gateway; the X-Service-Key still goes in the synthetic HTTP event so
    signatures.create's own auth decorator runs unchanged."""
    fn = resolve_function_name("signatures", "create")
    payload = {
        # Signatures.create reads headers via event.get('headers') and
        # normalises to lowercase; the casing here is preserved for
        # readability but doesn't matter.
        "headers": {"X-Service-Key": _load_service_key()},
        "body": json.dumps(
            {
                "pdf_source_url": pdf_source_url,
                "signature_location": SIGNATURE_LOCATION,
                "signer_email": signer_email,
                "signer_name": signer_name,
                "service_caller": "processes",
                # Fase 6b will wire a callback_url pointing at
                # processes.signature_callback. Left null for now so we
                # can deploy this step independently.
                "callback_url": None,
            }
        ),
    }

    try:
        resp = invoke_sync(fn, payload)
    except LambdaInvokeError as e:
        Logger.log(
            "ERROR",
            f"signature_bridge: {fn} invoke failed ({e.error_type}): {e.detail}",
        )
        raise SignatureBridgeError("signatures_invoke_failed", e.error_type) from e

    status = resp.get("statusCode")
    if status != 201:
        # signatures.create only returns 201 on success; anything else is
        # a body/URL/auth validation error we didn't catch upstream.
        err = _decode_error_body(resp.get("body"))
        Logger.log(
            "ERROR",
            f"signature_bridge: {fn} returned status={status} error={err} "
            f"for process={process_id}",
        )
        raise SignatureBridgeError(
            "signatures_create_rejected", f"status={status} error={err}"
        )

    try:
        body = json.loads(resp["body"])
    except (KeyError, TypeError, json.JSONDecodeError) as e:
        raise SignatureBridgeError("signatures_bad_body", str(e)) from e

    for k in ("sign_id", "sign_url"):
        if not body.get(k):
            raise SignatureBridgeError(
                "signatures_missing_field", f"response is missing {k}"
            )
    return body


def _decode_error_body(body) -> str:
    """Best-effort extraction of the `error` field from a signatures
    response body so operators can see WHY it rejected the call."""
    if not body:
        return "<empty-body>"
    try:
        return json.loads(body).get("error", "<no-error-field>")
    except (TypeError, json.JSONDecodeError):
        return "<non-json-body>"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def open_ceremony_for_process(*, proc, user, bank) -> str:
    """Renders the CDT investment order for `proc`, uploads it, calls
    signatures.create and stores `sign_id` on the row. Returns the
    `sign_url` for the caller to send to the frontend.

    `proc.form_snapshot` MUST have been populated by the earlier
    `form -> documents` transition. If it is missing the PDF still
    renders (with dashes for the missing fields) but the audit trail
    will look weak; the caller can treat this as a soft warning.
    """
    if not user or not getattr(user, "email", None):
        raise SignatureBridgeError("user_missing_email")
    if bank is None or not getattr(bank, "name", None):
        raise SignatureBridgeError("bank_not_found")

    Logger.log(
        "INFO",
        f"signature_bridge: opening ceremony for process={proc.id} "
        f"user={user.email} bank={bank.name}",
    )

    pdf_bytes = build_investment_order(
        process=proc,
        form=proc.form_snapshot,
        user=user,
        bank_name=bank.name,
    )

    key = _upload_pdf(proc.id, pdf_bytes)
    url = _presign_get(key)

    result = _invoke_signatures_create(
        pdf_source_url=url,
        signer_email=user.email,
        signer_name=user.full_name,
        process_id=proc.id,
    )

    proc.sign_id = result["sign_id"]
    # The signatures.create response carries `hash_original` and
    # `expires_at` too; we don't persist them here because processes
    # doesn't need them for anything -- if we ever do, add columns
    # rather than repurposing existing ones.
    Logger.log(
        "INFO",
        f"signature_bridge: process={proc.id} bound to sign_id={result['sign_id'][:6]}",
    )
    return result["sign_url"]
