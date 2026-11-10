import json
from decimal import Decimal
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.processes import ProcessStage, Processes
from libs.utils.auth import require_auth, AuthsTypes
from libs.utils.lambda_invoke import LambdaInvokeError, invoke_sync


def _raise_for_response(response: dict, default_error: str) -> None:
    status_code = response.get("statusCode", 502)
    if status_code != 200:
        error_message = json.loads(response.get("body") or "{}").get("error") or default_error
        raise HandledError(error_message, status_code)


def _paid_amount(process_id) -> Decimal:
    try:
        response = invoke_sync(
            function_key="list_process_payments",
            payload={"body": json.dumps({"process_id": str(process_id)})},
            service="payments",
        )
    except LambdaInvokeError as e:
        raise HandledError("payments_unavailable", 502) from e

    _raise_for_response(response, "payments_lookup_failed")

    payments = json.loads(response["body"]).get("payments", [])

    return sum((Decimal(payment["amount"]) for payment in payments), Decimal("0"))


@handle_exceptions
@require_auth(AuthsTypes.USER)
def handler(event, context):

    user = event["user"]

    query_params = event.get("queryStringParameters") or {}

    try:
        process_id = UUID(query_params.get("process_id"))
    except (TypeError, ValueError):
        raise HandledError("invalid process id", 400)

    process = Processes.get_by_id_for_update(process_id)
    if process is None or process.user_id != user.id:
        raise HandledError("process_not_found", 404)

    if process.stage != ProcessStage.PAYMENT.value:
        raise HandledError("process_not_in_payment_stage", 409)

    paid = _paid_amount(process_id)

    stage = process.stage

    if paid >= process.amount:
        Processes.advance_to_review(process_id)
        stage = ProcessStage.REVIEW.value

    response = {
        "process_id": str(process_id),
        "amount": float(process.amount),
        "paid": float(paid),
        "pending": float(max(process.amount - paid, Decimal("0"))),
        "stage": stage,
    }

    return generate_response(response, 200)
