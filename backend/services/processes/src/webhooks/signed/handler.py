import json
from uuid import UUID

from libs.core.logger import Logger
from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.processes import ProcessStage, Processes

TERMINAL_STAGES = ("SIGNED", "FAILED")


@handle_exceptions
def handler(event, context):

    body = json.loads(event.get("body") or "{}")

    try:
        signature_id = UUID(body.get("signature_id"))
    except (TypeError, ValueError):
        raise HandledError("invalid signature_id", 400)

    stage = body.get("stage")
    if stage not in TERMINAL_STAGES:
        raise HandledError(f"stage must be one of {list(TERMINAL_STAGES)}", 400)

    process = Processes.get_by_signature_id_for_update(signature_id)
    if process is None:
        raise HandledError("process_not_found", 404)

    if stage == "FAILED":
        Logger.log("WARNING", f"signed: signature {signature_id} FAILED for process {process.id}")
        return generate_response({"process_id": str(process.id), "advanced": False}, 200)

    advanced = process.stage == ProcessStage.SIGNATURE.value
    if advanced:
        Processes.advance_to_payment(process.id)

    response = {
        "process_id": str(process.id),
        "advanced": advanced,
    }

    return generate_response(response, 200)
