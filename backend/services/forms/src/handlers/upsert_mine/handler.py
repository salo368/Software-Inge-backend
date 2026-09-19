import json
from datetime import date
from decimal import Decimal, InvalidOperation

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.forms import Forms
from libs.utils.auth import require_auth

DOCUMENT_TYPES = {"CC", "CE", "PASAPORTE", "TI"}

REQUIRED_STRINGS = (
    "full_name", "document_type", "document_number", "phone",
    "address", "city", "occupation", "economic_activity", "source_of_funds",
)
REQUIRED_MONEY = ("monthly_income", "monthly_expenses", "total_assets", "total_liabilities")


@handle_exceptions
@require_auth
def handler(event, context):
    body = json.loads(event.get("body") or "{}")

    for field in REQUIRED_STRINGS:
        value = body.get(field)
        if not isinstance(value, str) or not value.strip():
            raise HandledError(f"{field} is required", 400)

    doc_type = body["document_type"].strip().upper()
    if doc_type not in DOCUMENT_TYPES:
        raise HandledError(f"document_type must be one of {sorted(DOCUMENT_TYPES)}", 400)

    birth_raw = body.get("birth_date")
    try:
        birth_date = date.fromisoformat(str(birth_raw))
    except (TypeError, ValueError):
        raise HandledError("birth_date must be ISO yyyy-mm-dd", 400)
    if birth_date >= date.today():
        raise HandledError("birth_date must be in the past", 400)

    money = {}
    for field in REQUIRED_MONEY:
        try:
            money[field] = Decimal(str(body.get(field)))
        except (TypeError, InvalidOperation):
            raise HandledError(f"{field} must be a number", 400)
        if money[field] < 0:
            raise HandledError(f"{field} must be >= 0", 400)

    is_peps = bool(body.get("is_peps", False))

    row = Forms.upsert(
        event["user"].id,
        full_name=body["full_name"].strip(),
        birth_date=birth_date,
        document_type=doc_type,
        document_number=body["document_number"].strip(),
        phone=body["phone"].strip(),
        address=body["address"].strip(),
        city=body["city"].strip(),
        occupation=body["occupation"].strip(),
        economic_activity=body["economic_activity"].strip(),
        source_of_funds=body["source_of_funds"].strip(),
        is_peps=is_peps,
        **money,
    )
    return generate_response({"form": row.public_dict()})
