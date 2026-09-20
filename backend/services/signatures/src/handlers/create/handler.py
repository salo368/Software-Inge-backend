"""Opens a signature ceremony for a process sitting in the `signature` stage.

Renders the investment order, parks it in S3 and emails the signer a link.
Calling it again on a process that already has an unfinished ceremony returns
that one instead of stacking duplicates.
"""
import boto3
import json
import os
import secrets
from uuid import UUID

from libs.core.mailer import send_email
from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.core.s3 import presign_download, upload_from_bytes
from libs.orm.banks import Banks
from libs.orm.forms import Forms
from libs.orm.processes import Processes
from libs.orm.signatures import Signatures
from libs.utils.auth import require_auth
from utils.emails import sign_request_html
from utils.investment_order import (
    SIGNATURE_PAGE,
    SIGNATURE_X_PCT,
    SIGNATURE_Y_PCT,
    build_investment_order,
)

BUCKET = os.environ["FILES_BUCKET"]
STAGE = os.environ.get("STAGE", "dev")
_base_url_cache: str | None = None


def _frontend_url() -> str:
    """Where the SPA lives, published by the frontend stack on deploy."""
    global _base_url_cache
    if _base_url_cache is None:
        try:
            resp = boto3.client("ssm").get_parameter(Name=f"/cdts/{STAGE}/frontend/url")
            _base_url_cache = resp["Parameter"]["Value"].rstrip("/")
        except Exception:
            _base_url_cache = ""
    return _base_url_cache


def _sign_url(event, token: str) -> str:
    """The SPA uses hash routing, so the emailed link has to carry the `#`."""
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    base = _frontend_url() or (headers.get("origin") or "").rstrip("/")
    return f"{base}/#/firmar/{token}"


@handle_exceptions
@require_auth
def handler(event, context):
    body = json.loads(event.get("body") or "{}")
    try:
        pid = UUID(body.get("process_id"))
    except (TypeError, ValueError):
        raise HandledError("invalid process id", 400)

    user = event["user"]
    proc = Processes.get_by_id(pid)
    if proc is None or proc.user_id != user.id:
        raise HandledError("process_not_found", 404)
    if proc.stage != "signature":
        raise HandledError("process_not_in_signature_stage", 409)

    existing = Signatures.get_active_for_process(proc.id)
    if existing is not None and existing.stage != "signed":
        return generate_response({
            "signature": existing.public_dict(),
            "sign_url": _sign_url(event, existing.token),
            "reused": True,
        })

    bank = Banks.get_by_id(proc.bank_id)
    bank_name = bank.name if bank else "Entidad financiera"
    snapshot = proc.form_snapshot
    if not snapshot:
        form = Forms.get_by_user(user.id)
        snapshot = form.public_dict() if form else None

    token = secrets.token_urlsafe(24)
    pdf_key = f"signatures/{token}/investment-order.pdf"
    upload_from_bytes(
        BUCKET,
        pdf_key,
        build_investment_order(process=proc, form=snapshot, user=user, bank_name=bank_name),
        "application/pdf",
    )

    row = Signatures.create(
        process_id=proc.id,
        email=user.email,
        pdf_key=pdf_key,
        page=SIGNATURE_PAGE,
        pos_x=SIGNATURE_X_PCT,
        pos_y=SIGNATURE_Y_PCT,
        token=token,
    )

    sign_url = _sign_url(event, token)
    emailed = send_email(
        user.email,
        f"Firma tu orden de inversión · {bank_name}",
        sign_request_html(
            name=(snapshot or {}).get("full_name") or user.full_name,
            bank_name=bank_name,
            amount=proc.amount,
            term_days=proc.term_days,
            rate=proc.rate,
            sign_url=sign_url,
        ),
    )

    return generate_response({
        "signature": row.public_dict(),
        "sign_url": sign_url,
        "pdf_url": presign_download(BUCKET, pdf_key),
        "emailed": emailed,
    }, 201)
