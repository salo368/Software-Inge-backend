"""Internal worker (invoke-only, no HTTP) that notifies a single,
preconfigured webhook whenever a signature reaches a terminal state
(SIGNED or FAILED). Invoked asynchronously from every place that sets
one of those two stages: sign_doc (SIGNED), and resolve_otp /
check_signature_timeout / check_signing_timeout (FAILED).

The webhook URL is NOT per-signature (unlike the legacy service's old
callback_url column) -- it's one fixed endpoint for the whole project,
read from SSM. The param isn't provisioned yet (no consumer exists),
so `_load_webhook_url` returning None just means "skip, log a
WARNING" -- the same "feature disabled until provisioned" pattern
already used for SSM_DEBUG_OTP_KEY_PATH in set_otp.
"""
import os
from typing import Optional

import boto3
import requests

from libs.core.logger import Logger

SSM_SIGN_TRIGGER_PATH = os.environ.get("SSM_SIGN_TRIGGER_PATH")

_WEBHOOK_TIMEOUT_S = 10

_webhook_url: Optional[str] = None
_webhook_url_loaded = False


def _load_webhook_url() -> Optional[str]:
    global _webhook_url, _webhook_url_loaded
    if _webhook_url_loaded:
        return _webhook_url
    _webhook_url_loaded = True
    if not SSM_SIGN_TRIGGER_PATH:
        return None
    try:
        resp = boto3.client("ssm").get_parameter(Name=SSM_SIGN_TRIGGER_PATH)
        value = (resp["Parameter"]["Value"] or "").strip()
        _webhook_url = value or None
    except Exception as e:
        Logger.log(
            "WARNING",
            f"sign_trigger: webhook URL unavailable at {SSM_SIGN_TRIGGER_PATH} ({type(e).__name__})",
        )
        _webhook_url = None
    return _webhook_url


def handler(event, context):
    signature_id = (event or {}).get("signature_id")
    stage = (event or {}).get("stage")
    if not signature_id or stage not in ("SIGNED", "FAILED"):
        Logger.log("ERROR", f"sign_trigger: bad payload {event!r}")
        return {"ok": False, "error": "bad_payload"}

    webhook_url = _load_webhook_url()
    if not webhook_url:
        Logger.log("WARNING", f"sign_trigger: no webhook configured, dropping signature_id={signature_id}")
        return {"ok": False, "skipped": True}

    body = {"signature_id": str(signature_id), "stage": stage}
    try:
        resp = requests.post(webhook_url, json=body, timeout=_WEBHOOK_TIMEOUT_S)
    except requests.RequestException as e:
        Logger.log("ERROR", f"sign_trigger: webhook POST failed for signature_id={signature_id}: {e}")
        return {"ok": False, "error": "webhook_unreachable"}

    if not (200 <= resp.status_code < 300):
        Logger.log(
            "ERROR",
            f"sign_trigger: webhook returned {resp.status_code} for signature_id={signature_id}",
        )
        return {"ok": False, "error": f"webhook_status_{resp.status_code}"}

    return {"ok": True, "signature_id": str(signature_id), "stage": stage}
