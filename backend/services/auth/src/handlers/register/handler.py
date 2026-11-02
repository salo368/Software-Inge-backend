import json

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.user_credentials import UserCredentials
from libs.orm.users import Users
from libs.utils.auth import issue_token
from libs.utils.passwords import hash_password
from libs.utils.validators import password_reason, valid_email


@handle_exceptions
def handler(event, context):

    body = json.loads(event.get("body") or "{}")

    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    full_name = (body.get("full_name") or "").strip()

    if not email or not password or not full_name:
        raise HandledError("missing_fields", 400)

    if not valid_email(email):
        raise HandledError("invalid_email", 400)

    if reason := password_reason(password):
        raise HandledError(reason, 400)

    if Users.get_by_email(email):
        raise HandledError("email_taken", 409)

    user = Users.create(email=email, full_name=full_name)
    UserCredentials.create(user_id=user.id, password_hash=hash_password(password))

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

    return generate_response(response, 201)
