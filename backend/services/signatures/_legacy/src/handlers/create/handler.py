"""Opens a signature ceremony from a source PDF supplied by presigned URL.

Called service-to-service via `X-Service-Key`. This is the ONLY endpoint
that requires the M2M shared secret; every other endpoint uses the
sign_id as the credential.

Flow:
  1. Validate body (pdf_source_url, signature_location, signer_email,
     optional callback_url, optional signer_name, optional
     service_caller).
  2. Download the source PDF from `pdf_source_url` and verify it is a
     PDF by magic bytes.
  3. Compute SHA-256 of the source bytes (`hash_original`).
  4. Generate `sign_id` locally (32-byte urlsafe token) and park a copy
     of the PDF in signatures' own bucket at
     `transactions/{sign_id}/original.pdf`. S3 first, DB second: an S3
     failure leaves no orphan row, and a DB failure leaves an orphan
     object that the 30-day lifecycle cleans automatically.
  5. Persist the row.
  6. Build `sign_url = <frontend_base>/sign/{sign_id}` from the frontend
     URL stored in SSM.
  7. Return {sign_id, sign_url, hash_original, expires_at}. The caller
     is responsible for delivering the sign_url to the signer (email,
     in-app, whatever). Signatures never sends the initial "please
     sign" notification -- only the OTP later on.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Optional

import boto3
import requests

from libs.core.logger import Logger
from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.signatures import Signatures, new_sign_id

from utils.auth import require_service_key


SIGNATURES_BUCKET = os.environ["SIGNATURES_BUCKET"]
STAGE = os.environ.get("STAGE", "dev")
SSM_FRONTEND_PATH = os.environ.get("SSM_FRONTEND_PATH", f"/cdts/{STAGE}/frontend")

# Warm-cache the frontend URL because it doesn't change per request and
# hitting SSM on every invocation adds ~50ms.
_frontend_url_cache: Optional[str] = None


def _frontend_url() -> str:
    global _frontend_url_cache
    if _frontend_url_cache is not None:
        return _frontend_url_cache
    try:
        resp = boto3.client("ssm").get_parameter(Name=f"{SSM_FRONTEND_PATH}/url")
        _frontend_url_cache = resp["Parameter"]["Value"].rstrip("/")
    except Exception as e:  # pragma: no cover - logged and treated as "" below
        Logger.log("WARNING", f"create: could not load frontend url: {e}")
        _frontend_url_cache = ""
    return _frontend_url_cache


def _reset_frontend_url_cache_for_tests() -> None:
    """Test hook: forces the next call to re-fetch from SSM."""
    global _frontend_url_cache
    _frontend_url_cache = None


def _valid_signature_location(loc) -> bool:
    """{page: int>=1, x_pct: 0-100, y_pct: 0-100, [width_pct, height_pct]}."""
    if not isinstance(loc, dict):
        return False
    try:
        page = int(loc["page"])
        x_pct = float(loc["x_pct"])
        y_pct = float(loc["y_pct"])
    except (KeyError, TypeError, ValueError):
        return False
    if page < 1:
        return False
    if not (0 <= x_pct <= 100 and 0 <= y_pct <= 100):
        return False
    for k in ("width_pct", "height_pct"):
        if k in loc:
            try:
                v = float(loc[k])
            except (TypeError, ValueError):
                return False
            if not (0 < v <= 100):
                return False
    return True


def _valid_callback_url(url) -> bool:
    """Optional. If present must be https and reasonably short."""
    if url is None:
        return True
    if not isinstance(url, str):
        return False
    if not url.startswith("https://"):
        return False
    if len(url) > 2000:
        return False
    return True


def _valid_email(v) -> bool:
    return isinstance(v, str) and "@" in v and 3 <= len(v) <= 254


@handle_exceptions
@require_service_key
def handler(event, context):
    body = json.loads(event.get("body") or "{}")

    pdf_source_url = body.get("pdf_source_url")
    signature_location = body.get("signature_location")
    signer_email = body.get("signer_email")
    signer_name = body.get("signer_name")
    callback_url = body.get("callback_url")
    service_caller = body.get("service_caller")

    if not (isinstance(pdf_source_url, str) and pdf_source_url.startswith("https://")):
        raise HandledError("invalid_pdf_source_url", 400)
    if not _valid_signature_location(signature_location):
        raise HandledError("invalid_signature_location", 400)
    if not _valid_email(signer_email):
        raise HandledError("invalid_signer_email", 400)
    if not _valid_callback_url(callback_url):
        raise HandledError("invalid_callback_url", 400)

    # Download the source PDF. Short timeout because the caller is inside
    # AWS and should be serving a presigned URL that resolves fast.
    try:
        resp = requests.get(pdf_source_url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        Logger.log("WARNING", f"create: could not download pdf_source_url: {e}")
        raise HandledError("could_not_download_source_pdf", 400)

    pdf_bytes = resp.content
    if len(pdf_bytes) < 100 or not pdf_bytes.startswith(b"%PDF-"):
        raise HandledError("source_is_not_a_pdf", 400)

    hash_original = hashlib.sha256(pdf_bytes).hexdigest()

    # Order: sign_id -> S3 upload -> DB write. See module docstring for
    # rationale (orphan-avoidance).
    sign_id = new_sign_id()
    s3_key = f"transactions/{sign_id}/original.pdf"
    try:
        boto3.client("s3").put_object(
            Bucket=SIGNATURES_BUCKET,
            Key=s3_key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
    except Exception as e:
        Logger.log("ERROR", f"create: S3 upload failed: {e}")
        raise HandledError("could_not_persist_source_pdf", 500)

    row = Signatures.create(
        sign_id=sign_id,
        signer_email=signer_email,
        signer_name=signer_name,
        signature_location=signature_location,
        hash_original=hash_original,
        callback_url=callback_url,
        service_caller=service_caller,
    )

    base = _frontend_url()
    if not base:
        raise HandledError("frontend_url_not_configured", 500)
    sign_url = f"{base}/sign/{row.sign_id}"

    return generate_response(
        {
            "sign_id": row.sign_id,
            "sign_url": sign_url,
            "hash_original": hash_original,
            "expires_at": row.expires_at.isoformat(),
        },
        201,
    )
