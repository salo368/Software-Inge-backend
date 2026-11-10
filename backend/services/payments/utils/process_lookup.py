from __future__ import annotations

import json

from libs.core.responses import HandledError
from libs.utils.lambda_invoke import LambdaInvokeError, invoke_sync

PAYMENT_STAGE = "PAYMENT"


def get_payable_process(event, process_id) -> dict:
    """The process (as processes.get_processes returns it) if it belongs to
    the caller and is waiting for payment. Forwards the caller's
    Authorization header, so processes does the ownership check."""
    try:
        response = invoke_sync(
            function_key="get_processes",
            payload={"headers": event.get("headers")},
            service="processes",
        )
    except LambdaInvokeError as e:
        raise HandledError("processes_unavailable", 502) from e

    if response.get("statusCode") != 200:
        error_message = json.loads(response.get("body") or "{}").get("error")
        raise HandledError(error_message, response.get("statusCode", 502))

    processes = json.loads(response["body"]).get("processes", [])
    process = next((p for p in processes if p["id"] == str(process_id)), None)

    if process is None:
        raise HandledError("process_not_found", 404)

    if process["stage"] != PAYMENT_STAGE:
        raise HandledError("process_not_in_payment_stage", 409)

    return process
