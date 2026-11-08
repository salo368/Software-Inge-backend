import json
from decimal import Decimal, InvalidOperation
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.payments import Payments
from libs.utils.auth import require_auth
from utils.process_lookup import get_payable_process
from utils.s3_keys import payment_key_prefix


@handle_exceptions
@require_auth
def handler(event, context):

    body = json.loads(event.get("body") or "{}")

    try:
        process_id = UUID(body.get("process_id"))
    except (TypeError, ValueError):
        raise HandledError("invalid process id", 400)

    s3_key = body.get("s3_key")
    if not s3_key or not isinstance(s3_key, str):
        raise HandledError("s3_key is required", 400)
    if not s3_key.startswith(payment_key_prefix(process_id)):
        raise HandledError("s3_key does not belong to this process", 400)

    try:
        amount = Decimal(str(body.get("amount")))
    except InvalidOperation:
        raise HandledError("invalid_amount", 400)
    if not amount.is_finite() or amount <= 0:
        raise HandledError("invalid_amount", 400)

    get_payable_process(event, process_id)

    payment = Payments.create(process_id=process_id, amount=amount, s3_file=s3_key)

    response = {
        "id": payment.id,
        "process_id": payment.process_id,
        "amount": float(payment.amount),
        "s3_file": payment.s3_file,
    }

    return generate_response(response, 200)
