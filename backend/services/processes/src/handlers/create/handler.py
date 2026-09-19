import json
from decimal import Decimal, InvalidOperation

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.banks import Banks
from libs.orm.processes import Processes
from libs.utils.auth import require_auth

MIN_AMOUNT = Decimal("100000")
MAX_AMOUNT = Decimal("5000000000")
VALID_TERMS = {30, 60, 90, 120, 180, 270, 360, 540, 720}


@handle_exceptions
@require_auth
def handler(event, context):
    body = json.loads(event.get("body") or "{}")

    try:
        bank_id = int(body.get("bank_id"))
    except (TypeError, ValueError):
        raise HandledError("bank_id must be an integer", 400)

    try:
        amount = Decimal(str(body.get("amount")))
    except (TypeError, InvalidOperation):
        raise HandledError("amount must be a number", 400)
    if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
        raise HandledError("amount out of range", 400)

    try:
        term_days = int(body.get("term_days"))
    except (TypeError, ValueError):
        raise HandledError("term_days must be an integer", 400)
    if term_days not in VALID_TERMS:
        raise HandledError(f"term_days must be one of {sorted(VALID_TERMS)}", 400)

    try:
        rate = Decimal(str(body.get("rate")))
    except (TypeError, InvalidOperation):
        raise HandledError("rate must be a number", 400)
    if rate <= 0 or rate > 30:
        raise HandledError("rate out of range", 400)

    bank = Banks.get_by_id(bank_id)
    if bank is None or not bank.is_active:
        raise HandledError("bank_not_found", 404)

    row = Processes.create(
        user_id=event["user"].id,
        bank_id=bank_id,
        amount=amount,
        term_days=term_days,
        rate=rate,
    )
    return generate_response({"process": row.public_dict()}, 201)
