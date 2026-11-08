import json
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.payments import Payments


@handle_exceptions
def handler(event, context):

    body = json.loads(event.get("body") or "{}")

    try:
        process_id = UUID(body.get("process_id"))
    except (TypeError, ValueError):
        raise HandledError("invalid process id", 400)

    rows = Payments.list_by_process(process_id)

    payments = []
    for row in rows:
        payments.append({
            "id": row.id,
            "amount": str(row.amount),
            "s3_file": row.s3_file,
        })

    response = {
        "payments": payments,
    }

    return generate_response(response, 200)
