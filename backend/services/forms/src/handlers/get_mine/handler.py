from libs.core.responses import generate_response, handle_exceptions
from libs.orm.forms import Forms
from libs.utils.auth import require_auth


@handle_exceptions
@require_auth
def handler(event, context):
    row = Forms.get_by_user(event["user"].id)
    return generate_response({"form": row.public_dict() if row else None})
