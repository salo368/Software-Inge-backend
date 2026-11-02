import json
from decimal import Decimal, InvalidOperation

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.banks import Banks
from libs.orm.processes import Processes
from libs.utils.auth import require_auth
from libs.utils.lambda_invoke import LambdaInvokeError, invoke_sync


@handle_exceptions
@require_auth
def handler(event, context):

    user = event.get("user")

    body = json.loads(event.get("body") or "{}")

    bank_id = body.get("bank_id")
    amount = body.get("amount")
    term = body.get("term")

    if not bank_id or not amount or not term:
        raise HandledError("Missing required fields", 400)

    try:
        simulation_response = invoke_sync(
            function_key="simulate",
            payload={
                "queryStringParameters": {"amount": str(amount), "term": str(term)}
            },
            service="banks",
        )
    except LambdaInvokeError as e:
        raise HandledError("simulation_unavailable", 502) from e

    if simulation_response.get("statusCode") != 200:
        error_message = json.loads(simulation_response.get("body") or "{}").get("error")
        error_code = simulation_response.get("statusCode", 502)
        raise HandledError(error_message, error_code)

    simulation_result = json.loads(simulation_response["body"])
    simulation_banks = simulation_result.get("banks", {})

    simulation = simulation_banks.get(str(bank_id))
    if not simulation:
        raise HandledError("Bank not available for the given amount and term", 400)

    process = Processes.create(
        user_id=user.id,
        bank_id=bank_id,
        amount=Decimal(str(amount)),
        term=int(term),
        rate=Decimal(str(simulation["rate"])),
    )

    response = {
        "id": process.id,
        "bank_id": process.bank_id,
        "amount": float(process.amount),
        "term": process.term,
        "rate": float(process.rate),
        "stage": process.stage,
        "created_at": process.created_at,
    }

    return generate_response(response, 200)
