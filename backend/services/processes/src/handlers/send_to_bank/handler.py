from libs.core.logger import Logger
from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.processes import ProcessStage, Processes
from libs.utils.auth import AuthsTypes, require_auth
from libs.utils.params import request_params, uuid_param


@handle_exceptions
@require_auth(AuthsTypes.INTERNAL)
def handler(event, context):

    admin = event["admin"]

    process_id = uuid_param(request_params(event), "process_id", "invalid process id")

    # Row lock until commit: two admins approving the same process serialize,
    # and the second one sees SENT_TO_BANK and gets a 409.
    process = Processes.get_by_id_for_update(process_id)
    if process is None:
        raise HandledError("process_not_found", 404)

    if process.stage != ProcessStage.REVIEW.value:
        raise HandledError("process_not_in_review_stage", 409)

    updated = Processes.advance_to_sent_to_bank(process_id)

    Logger.log("INFO", f"send_to_bank: admin {admin.id} moved process {process_id} REVIEW -> SENT_TO_BANK")

    response = {
        "process_id": str(process_id),
        "stage": updated.stage,
    }

    return generate_response(response, 200)
