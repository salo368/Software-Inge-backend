from libs.core.responses import generate_response, handle_exceptions
from libs.orm.processes import Processes
from libs.utils.auth import require_any_auth
from libs.utils.params import request_params, uuid_param


@handle_exceptions
@require_any_auth
def handler(event, context):

    user = event.get("user")
    if user is not None:
        user_id = user.id
    else:
        user_id = uuid_param(request_params(event), "user_id", "invalid user id")

    rows = Processes.list_by_user(user_id)

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
