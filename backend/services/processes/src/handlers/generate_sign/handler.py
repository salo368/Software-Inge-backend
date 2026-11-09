import base64
import html
import json
import os
from urllib.parse import urlencode
from uuid import UUID

import boto3
import requests

from libs.core.logger import Logger
from libs.core.mailer import send_email
from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.processes import ProcessStage, Processes
from libs.utils.lambda_invoke import LambdaInvokeError, invoke_sync

_DOWNLOAD_TIMEOUT_S = 10
_FRONTEND_URL_PARAM = f"/cdts/{os.environ.get('STAGE', 'dev')}/frontend/url"
_SIGN_EMAIL_SUBJECT = "Firma tu orden de inversión"
_SIGN_EMAIL_HTML = """\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:520px;margin:auto;padding:24px;color:#222;">
  <p>Hola {name},</p>
  <p>Tu orden de inversión está lista para firmar. Puedes hacerlo desde tu computador
  o desde tu celular con el siguiente enlace:</p>
  <p><a href="{url}" style="display:inline-block;padding:12px 20px;background:#111;color:#fff;
  border-radius:8px;text-decoration:none;">Firmar orden de inversión</a></p>
  <p style="color:#555;font-size:13px;">Si el botón no funciona, copia este enlace en tu navegador:<br>{url}</p>
</div>"""


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


def _frontend_url() -> str:
    return boto3.client("ssm").get_parameter(Name=_FRONTEND_URL_PARAM)["Parameter"]["Value"].rstrip("/")


def _email_sign_link(form: dict, signature_id: str, process_id: UUID) -> bool:

    email = (form.get("email") or "").strip()
    if not email:
        Logger.log("WARNING", f"generate_sign: no email in form, sign link not sent for signature_id={signature_id[:8]}")
        return False

    try:
        base = _frontend_url()
        # return_url must be same-origin with the signing app (it validates that).
        query = urlencode({"return_url": f"{base}/portal/process/{process_id}", "email": email})
        url = f"{base}/sign/{signature_id}?{query}"
        body = _SIGN_EMAIL_HTML.format(name=html.escape(_signatory_name(form)), url=html.escape(url))
        return send_email(email, _SIGN_EMAIL_SUBJECT, body)
    except Exception as e:
        Logger.log("ERROR", f"generate_sign: could not email sign link for signature_id={signature_id[:8]}: {e}")
        return False


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

    email_sent = _email_sign_link(form, signature_id, process_id)

    response = {
        "process_id": str(process_id),
        "signature_id": signature_id,
        "email_sent": email_sent,
    }

    return generate_response(response, 200)
