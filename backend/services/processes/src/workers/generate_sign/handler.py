"""Internal worker (invoke-only, no HTTP).

Invoked asynchronously by `get_required_files` once all required files
for a process are uploaded. Fetches the bank's empty investment order,
populates it with the process's form answers and commercial terms, and
opens a signature ceremony for the populated document, storing the
resulting signature_id on the process.

Never marks the process FAILED on an internal error -- it just leaves
it at DOCUMENTS. `get_required_files` is the only caller and only
invokes this worker while the process is still at DOCUMENTS, so the
next time the front end polls it (e.g. the user revisits the page),
the same guard lets this worker run again -- a built-in retry, no
separate timeout/safety-net worker needed.
"""
from __future__ import annotations

import base64
import json

import requests

from libs.core.db import db_session
from libs.core.logger import Logger
from libs.orm.processes import ProcessStage, Processes
from libs.utils.lambda_invoke import invoke_sync
from utils.investment_order import SIGNATURE_LOCATION, populate_investment_order

_TEMPLATE_FETCH_TIMEOUT_S = 10


def _signatory_name(form: dict) -> str:
    parts = [form.get("name"), form.get("second_name"), form.get("last_name"), form.get("second_last_name")]
    name = " ".join(p for p in parts if p)
    return name or "Titular"


def _fetch_bank(bank_id) -> dict:
    resp = invoke_sync(
        "get_bank", {"queryStringParameters": {"bank_id": str(bank_id)}}, service="banks",
    )
    if resp.get("statusCode") != 200:
        raise RuntimeError(f"get_bank({bank_id}) returned {resp.get('statusCode')}: {resp.get('body')}")
    return json.loads(resp["body"])


def _fetch_template(io_url: str) -> bytes:
    resp = requests.get(io_url, timeout=_TEMPLATE_FETCH_TIMEOUT_S)
    resp.raise_for_status()
    return resp.content


def _create_signature(pdf_bytes: bytes, signatory: str) -> str:
    event = {
        "queryStringParameters": {
            "sign_location": json.dumps(SIGNATURE_LOCATION),
            "signatory": signatory,
        },
        "body": base64.b64encode(pdf_bytes).decode("ascii"),
        "isBase64Encoded": True,
    }
    resp = invoke_sync("create_signature", event, service="signatures")
    if resp.get("statusCode") != 200:
        raise RuntimeError(f"create_signature returned {resp.get('statusCode')}: {resp.get('body')}")
    return json.loads(resp["body"])["id"]


def handler(event, context):
    process_id = (event or {}).get("process_id")
    if not process_id:
        Logger.log("ERROR", "generate_sign: missing process_id in payload")
        return {"ok": False, "error": "missing_process_id"}

    process = Processes.get_by_id(process_id)
    if process is None:
        Logger.log("ERROR", f"generate_sign: no row for process_id={process_id}")
        return {"ok": False, "error": "process_not_found"}

    if process.stage != ProcessStage.DOCUMENTS.value:
        Logger.log(
            "WARNING",
            f"generate_sign: process_id={process_id} at stage={process.stage}, "
            "expected DOCUMENTS; skipping (already handled or not ready)",
        )
        return {"ok": False, "skipped": True, "stage": process.stage}

    try:
        bank = _fetch_bank(process.bank_id)
        io_url = bank.get("io_url")
        if not io_url:
            raise RuntimeError(f"bank {process.bank_id} has no io_url configured")

        template_pdf = _fetch_template(io_url)
        populated_pdf = populate_investment_order(
            template_pdf,
            form=process.submitted_form or {},
            amount=process.amount,
            term=process.term,
            rate=process.rate,
        )
        signatory = _signatory_name(process.submitted_form or {})
        signature_id = _create_signature(populated_pdf, signatory)
    except Exception as e:
        Logger.log("ERROR", f"generate_sign: process_id={process_id} failed: {e}")
        db_session.rollback()
        return {"ok": False, "error": "internal_error"}

    Processes.set_signature_id(process_id, signature_id)
    db_session.commit()
    Logger.log("INFO", f"generate_sign: process_id={process_id} -> signature_id={signature_id}")
    return {"ok": True, "process_id": str(process_id), "signature_id": signature_id}
