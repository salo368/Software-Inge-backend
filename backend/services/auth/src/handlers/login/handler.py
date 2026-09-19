import json

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.users import Users
from libs.utils.auth import issue_token, verify_password


@handle_exceptions
def handler(event, context):
    body = json.loads(event.get("body") or "{}")
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        raise HandledError("missing_fields", 400)

    user = Users.get_by_email(email)
    # Same code for missing user and wrong password to prevent enumeration.
    if user is None or not verify_password(password, user.password_hash):
        raise HandledError("invalid_credentials", 401)

    token, expires_at = issue_token(user.id)

    return generate_response({
        "user": user.public_dict(),
        "token": token,
        "expires_at": expires_at.isoformat(),
    })
