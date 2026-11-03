from libs.core.responses import generate_response, handle_exceptions
from libs.orm.processes import Processes
from libs.utils.auth import require_auth


@handle_exceptions
@require_auth
def handler(event, context):

    user = event["user"]

    rows = Processes.list_by_user(user.id)

    processes = []
    for row in rows:
        processes.append({
            "id": row.id,
            "bank_id": row.bank_id,
            "amount": float(row.amount),
            "term": row.term,
            "rate": float(row.rate),
            "stage": row.stage,
            "signature_id": row.signature_id,
            "created_at": row.created_at,
        })

    response = {
        "processes": processes,
    }

    return generate_response(response, 200)
