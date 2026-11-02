from libs.core.responses import generate_response, handle_exceptions
from libs.utils.auth import require_auth


@handle_exceptions
@require_auth
def handler(event, context):

    user = event.get("user")

    response = {
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat(),
        }
    }

    return generate_response(response, 200)
