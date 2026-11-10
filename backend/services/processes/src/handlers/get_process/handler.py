from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.processes import Processes
from libs.utils.auth import require_any_auth
from libs.utils.params import request_params, uuid_param


@handle_exceptions
@require_any_auth
def handler(event, context):

    process_id = uuid_param(request_params(event), "process_id", "invalid process id")

    process = Processes.get_by_id(process_id)

    user = event.get("user")
    if process is None or (user is not None and process.user_id != user.id):
        raise HandledError("process_not_found", 404)

    response = {
        "process": {
            "id": process.id,
            "user_id": process.user_id,
            "bank_id": process.bank_id,
            "amount": float(process.amount),
            "term": process.term,
            "rate": float(process.rate),
            "stage": process.stage,
            "signature_id": process.signature_id,
            "submitted_form": process.submitted_form,
            "created_at": process.created_at,
            "updated_at": process.updated_at,
        },
    }

    return generate_response(response, 200)
