from libs.core.responses import generate_response, handle_exceptions
from libs.orm.processes import Processes
from libs.utils.auth import require_auth


@handle_exceptions
@require_auth
def handler(event, context):
    rows = Processes.list_by_user(event["user"].id)
    return generate_response({"processes": [r.public_dict() for r in rows]})
