import base64
import json
from uuid import UUID

import requests

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.processes import ProcessStage, Processes
from libs.utils.lambda_invoke import LambdaInvokeError, invoke_sync

_DOWNLOAD_TIMEOUT_S = 10


def _signatory_name(form: dict) -> str:
    parts = [form.get("name"), form.get("second_name"), form.get("last_name"), form.get("second_last_name")]
    name = " ".join(p for p in parts if p)
    return name or "Titular"


def _raise_for_response(response: dict, default_error: str) -> None:
    status_code = response.get("statusCode", 502)
    if status_code != 200:
        error_message = json.loads(response.get("body") or "{}").get("error") or default_error
        raise HandledError(error_message, status_code)


def _generate_raw_investment_order(process) -> dict:
    payload = {
        "body": json.dumps({
            "process_id": str(process.id),
            "bank_id": process.bank_id,
            "submitted_form": process.submitted_form,
            "amount": str(process.amount),
            "term": process.term,
            "rate": str(process.rate),
        }),
    }

    try:
        response = invoke_sync(
            function_key="generate_raw_investment_order",
            payload=payload,
            service="files",
        )
    except LambdaInvokeError as e:
        raise HandledError("files_unavailable", 502) from e

    _raise_for_response(response, "investment_order_generation_failed")

    return json.loads(response["body"])


def _download(url: str) -> bytes:
    try:
        response = requests.get(url, timeout=_DOWNLOAD_TIMEOUT_S)
        response.raise_for_status()
    except requests.RequestException as e:
        raise HandledError("investment_order_download_failed", 502) from e

    return response.content


def _create_signature(pdf_bytes: bytes, signatory: str, sign_location: list) -> str:
    event = {
        "queryStringParameters": {
            "sign_location": json.dumps(sign_location),
            "signatory": signatory,
        },
        "body": base64.b64encode(pdf_bytes).decode("ascii"),
        "isBase64Encoded": True,
    }

    try:
        response = invoke_sync(
            function_key="create_signature",
            payload=event,
            service="signatures",
        )
    except LambdaInvokeError as e:
        raise HandledError("signatures_unavailable", 502) from e

    _raise_for_response(response, "signature_creation_failed")

    return json.loads(response["body"])["id"]


@handle_exceptions
def handler(event, context):
  
    body = json.loads(event.get("body") or "{}")

    try:
        process_id = UUID(body.get("process_id"))
    except (TypeError, ValueError):
        raise HandledError("invalid process id", 400)

    process = Processes.get_by_id(process_id)
    if process is None:
        raise HandledError("process_not_found", 404)

    if process.stage != ProcessStage.DOCUMENTS.value:
        raise HandledError("process_not_in_documents_stage", 409)

    form = process.submitted_form or {}

    raw_investment_order = _generate_raw_investment_order(process)
    pdf_bytes = _download(raw_investment_order["url"])

    signature_id = _create_signature(
        pdf_bytes,
        _signatory_name(form),
        raw_investment_order["sign_location"],
    )

    Processes.set_signature_id(process_id, signature_id)

    response = {
        "process_id": str(process_id),
        "signature_id": signature_id,
    }

    return generate_response(response, 200)
