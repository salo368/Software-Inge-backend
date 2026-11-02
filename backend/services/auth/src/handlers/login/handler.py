import json

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.user_credentials import UserCredentials
from libs.orm.users import Users
from libs.utils.auth import issue_token
from libs.utils.passwords import verify_password


@handle_exceptions
def handler(event, context):

    body = json.loads(event.get("body") or "{}")

    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        raise HandledError("missing_fields", 400)

    user = Users.get_by_email(email)
    if user is None:
        raise HandledError("invalid_credentials", 401)

    credentials = UserCredentials.get_by_user_id(user.id)

    is_valid = credentials is not None and verify_password(password, credentials.password_hash)

    if not is_valid:
        raise HandledError("invalid_credentials", 401)

    token, expires_at = issue_token(user.id)

    response = {
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat(),
        },
        "token": token,
        "expires_at": expires_at.isoformat(),
    }
    
    return generate_response(response, 200)
    
