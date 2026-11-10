from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.processes import ProcessStage, Processes
from libs.utils.auth import AuthsTypes, require_auth
from libs.utils.params import paginated_response, pagination_params, request_params

_VALID_STAGES = {stage.value for stage in ProcessStage}


def _bank_id(params: dict):

    raw = params.get("bank_id")
    if raw is None or raw == "":
        return None

    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise HandledError("invalid_bank_id", 400)

    if value < 1:
        raise HandledError("invalid_bank_id", 400)

    return value


def _stages(params: dict) -> list[str]:
    """`stages` as a list (JSON body) or comma-separated string (query string)."""

    raw = params.get("stages")
    if raw is None or raw == "":
        return []

    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, list):
        raise HandledError("invalid_stages", 400)

    stages = []
    for item in raw:
        stage = str(item).strip().upper()
        if stage not in _VALID_STAGES:
            raise HandledError("invalid_stages", 400)
        if stage not in stages:
            stages.append(stage)

    return stages


def _applicant(form: dict | None) -> dict:
    """The form's main data, for the list row; nulls when the form is not filled yet."""

    form = form or {}
    name_parts = [form.get("name"), form.get("second_name"), form.get("last_name"), form.get("second_last_name")]

    return {
        "full_name": " ".join(p for p in name_parts if p) or None,
        "email": form.get("email"),
        "document_type": form.get("document_type"),
        "document_number": form.get("document_number"),
    }


@handle_exceptions
@require_auth(AuthsTypes.INTERNAL)
def handler(event, context):

    params = request_params(event)

    search = params.get("search") or ""
    if not isinstance(search, str):
        raise HandledError("invalid_search", 400)
    search = search.strip()

    bank_id = _bank_id(params)
    stages = _stages(params)
    limit, offset = pagination_params(params)

    total = Processes.count_search(bank_id, stages, search)
    rows = Processes.search(bank_id, stages, search, limit, offset)

    items = [
        {
            "id": row.id,
            "user_id": row.user_id,
            "bank_id": row.bank_id,
            "amount": float(row.amount),
            "term": row.term,
            "rate": float(row.rate),
            "stage": row.stage,
            "signature_id": row.signature_id,
            "applicant": _applicant(row.submitted_form),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]

    return generate_response(paginated_response(items, limit, offset, total), 200)
