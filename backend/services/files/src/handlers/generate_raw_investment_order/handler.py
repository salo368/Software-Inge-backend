from __future__ import annotations

import json
import os
from uuid import uuid4

import requests

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.core.s3 import presign_download, upload_from_bytes
from libs.orm.files import FileType
from libs.utils.lambda_invoke import invoke_sync
from utils.investment_order import SIGNATURE_LOCATION, populate_investment_order
from utils.s3_keys import build_file_key, build_file_metadata

BUCKET = os.environ["FILES_BUCKET"]
_TEMPLATE_FETCH_TIMEOUT_S = 10


def _fetch_bank(bank_id) -> dict:
    resp = invoke_sync(
        "get_bank", {"queryStringParameters": {"bank_id": str(bank_id)}}, service="banks",
    )
    if resp.get("statusCode") != 200:
        raise HandledError("bank_lookup_failed", 502)
    return json.loads(resp["body"])


def _fetch_template(io_url: str) -> bytes:
    resp = requests.get(io_url, timeout=_TEMPLATE_FETCH_TIMEOUT_S)
    resp.raise_for_status()
    return resp.content


@handle_exceptions
def handler(event, context):

    body = json.loads(event.get("body") or "{}")

    process_id = body.get("process_id")
    bank_id = body.get("bank_id")
    submitted_form = body.get("submitted_form")
    amount = body.get("amount")
    term = body.get("term")
    rate = body.get("rate")

    if not process_id or bank_id is None or submitted_form is None:
        raise HandledError("process_id, bank_id and submitted_form are required", 400)

    if amount is None or term is None or rate is None:
        raise HandledError("amount, term and rate are required", 400)

    bank = _fetch_bank(bank_id)
    io_url = bank.get("io_url")
    if not io_url:
        raise HandledError("bank_without_investment_order", 422)

    template_pdf = _fetch_template(io_url)
    populated_pdf = populate_investment_order(
        template_pdf,
        form=submitted_form,
        amount=amount,
        term=term,
        rate=rate,
    )

    key = build_file_key(process_id, FileType.RAW_INVESTMENT_ORDER, uuid4(), ".pdf")
    metadata = build_file_metadata(process_id, FileType.RAW_INVESTMENT_ORDER, "investment_order.pdf")

    upload_from_bytes(BUCKET, key, populated_pdf, "application/pdf", metadata=metadata)

    response = {
        "process_id": str(process_id),
        "key": key,
        "url": presign_download(BUCKET, key),
        "sign_location": SIGNATURE_LOCATION,
    }

    return generate_response(response, 200)
