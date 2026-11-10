import json
from uuid import UUID

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.files import FileType
from libs.orm.processes import ProcessStage, Processes
from libs.utils.auth import require_auth, AuthsTypes
from libs.utils.lambda_invoke import LambdaInvokeError, invoke_async, invoke_sync


def _required_file_types(submitted_form: dict) -> set:

    required = {FileType.BANK_CERT.value}

    if submitted_form.get("is_tax_declarant"):
        required.add(FileType.TAX_DECLARATION.value)

    if submitted_form.get("is_pep"):
        required.add(FileType.RUT.value)

    return required


@handle_exceptions
@require_auth(AuthsTypes.USER)
def handler(event, context):

    user = event["user"]

    query_params = event.get("queryStringParameters") or {}

    process_id_raw = query_params.get("process_id")
    try:
        process_id = UUID(process_id_raw)
    except (TypeError, ValueError):
        raise HandledError("invalid process id", 400)

    process = Processes.get_by_id(process_id)
    if process is None or process.user_id != user.id:
        raise HandledError("process_not_found", 404)

    required_types = _required_file_types(process.submitted_form or {})

    try:
        files_response = invoke_sync(
            function_key="list_process_files",
            payload={"body": json.dumps({"process_id": str(process_id)})},
            service="files",
        )
    except LambdaInvokeError as e:
        raise HandledError("files_lookup_unavailable", 502) from e

    if files_response.get("statusCode") != 200:
        error_message = json.loads(files_response.get("body") or "{}").get("error")
        error_code = files_response.get("statusCode", 502)
        raise HandledError(error_message, error_code)

    files = json.loads(files_response["body"]).get("files", [])
    uploaded_types = {f["file_type"] for f in files}

    status = {file_type: file_type in uploaded_types for file_type in required_types}

    if all(status.values()) and process.stage == ProcessStage.DOCUMENTS.value:
        try:
            invoke_async("generate_sign", {"body": json.dumps({"process_id": str(process_id)})})
        except LambdaInvokeError as e:
            raise HandledError("generate_sign_unavailable", 502) from e

    return generate_response(status, 200)
