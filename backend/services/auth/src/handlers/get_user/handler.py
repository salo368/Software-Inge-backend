from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.users import Users
from libs.utils.auth import AuthsTypes, require_auth
from libs.utils.params import request_params, uuid_param


@handle_exceptions
@require_auth(AuthsTypes.INTERNAL)
def handler(event, context):

    user_id = uuid_param(request_params(event), "user_id", "invalid user id")

    user = Users.get_by_id(user_id)
    if user is None:
        raise HandledError("user_not_found", 404)

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
