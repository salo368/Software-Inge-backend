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

    # Row lock until commit: concurrent approvals serialize, the loser gets a 409.
    process = Processes.get_by_id_for_update(process_id)
    if process is None:
        raise HandledError("process_not_found", 404)

    if process.stage != ProcessStage.SENT_TO_BANK.value:
        raise HandledError("process_not_in_sent_to_bank_stage", 409)

    updated = Processes.advance_to_completed(process_id)

    Logger.log("INFO", f"approve_cdt: admin {admin.id} moved process {process_id} SENT_TO_BANK -> COMPLETED")

    response = {
        "process_id": str(process_id),
        "stage": updated.stage,
    }

    return generate_response(response, 200)
