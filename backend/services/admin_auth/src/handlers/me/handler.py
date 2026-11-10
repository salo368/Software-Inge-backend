from libs.core.responses import generate_response, handle_exceptions
from libs.utils.auth import require_auth, AuthsTypes


@handle_exceptions
@require_auth(AuthsTypes.INTERNAL)
def handler(event, context):

    admin = event.get("admin")

    response = {
        "admin": {
            "id": admin.id,
            "email": admin.email,
            "full_name": admin.full_name,
            "created_at": admin.created_at.isoformat(),
            "updated_at": admin.updated_at.isoformat(),
        }
    }

    return generate_response(response, 200)
