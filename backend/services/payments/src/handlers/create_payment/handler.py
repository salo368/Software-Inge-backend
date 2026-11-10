import json
from decimal import Decimal, InvalidOperation
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.payments import Payments
from libs.utils.auth import require_auth, AuthsTypes
from utils.process_lookup import get_payable_process
from utils.s3_keys import payment_key_prefix


@handle_exceptions
@require_auth(AuthsTypes.USER)
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

    process = get_payable_process(event, process_id)

    # Serialize concurrent payments of this process, then check against what
    # is still owed so a transfer can never overshoot the process amount.
    Payments.lock_process(process_id)
    paid = sum((p.amount for p in Payments.list_by_process(process_id)), Decimal("0"))
    pending = Decimal(str(process["amount"])) - paid
    if amount > pending:
        raise HandledError("amount_exceeds_pending", 422)

    payment = Payments.create(process_id=process_id, amount=amount, s3_file=s3_key)

    response = {
        "id": payment.id,
        "process_id": payment.process_id,
        "amount": float(payment.amount),
        "s3_file": payment.s3_file,
    }

    return generate_response(response, 200)
