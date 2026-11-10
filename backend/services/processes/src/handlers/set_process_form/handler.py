import json
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.processes import ProcessStage, Processes
from libs.utils.auth import require_auth, AuthsTypes
from libs.utils.lambda_invoke import LambdaInvokeError, invoke_sync


@handle_exceptions
@require_auth(AuthsTypes.USER)
def handler(event, context):

    user = event["user"]

    body = json.loads(event.get("body") or "{}")

    process_id_raw = body.get("process_id")
    try:
        process_id = UUID(process_id_raw)
    except (TypeError, ValueError):
        raise HandledError("invalid process id", 400)

    process = Processes.get_by_id(process_id)
    if process is None or process.user_id != user.id:
        raise HandledError("process_not_found", 404)

    if process.stage not in (ProcessStage.FORM.value, ProcessStage.DOCUMENTS.value):
        raise HandledError("process_form_locked", 409)

    try:
        form_response = invoke_sync(
            function_key="get_form",
            payload={"headers": event.get("headers")},
            service="forms",
        )
    except LambdaInvokeError as e:
        raise HandledError("form_lookup_unavailable", 502) from e

    if form_response.get("statusCode") != 200:
        error_message = json.loads(form_response.get("body") or "{}").get("error")
        error_code = form_response.get("statusCode", 502)
        raise HandledError(error_message, error_code)

    form = json.loads(form_response["body"]).get("form")
    if not form:
        raise HandledError("form_required", 400)

    updated = Processes.set_submitted_form(process_id, form)

    response = {
        "id": updated.id,
        "stage": updated.stage,
        "submitted_form": updated.submitted_form,
    }

    return generate_response(response, 200)
