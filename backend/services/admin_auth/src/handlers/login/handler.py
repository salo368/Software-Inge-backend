import json

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.admin_credentials import AdminCredentials
from libs.orm.admins import Admins
from libs.utils.auth import issue_token, AuthsTypes
from libs.utils.passwords import verify_password


@handle_exceptions
def handler(event, context):

    body = json.loads(event.get("body") or "{}")

    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        raise HandledError("missing_fields", 400)

    admin = Admins.get_by_email(email)
    if admin is None:
        raise HandledError("invalid_credentials", 401)

    credentials = AdminCredentials.get_by_admin_id(admin.id)

    is_valid = credentials is not None and verify_password(password, credentials.password_hash)

    if not is_valid:
        raise HandledError("invalid_credentials", 401)

    token, expires_at = issue_token(admin.id, AuthsTypes.INTERNAL)

    response = {
        "admin": {
            "id": admin.id,
            "email": admin.email,
            "full_name": admin.full_name,
            "created_at": admin.created_at.isoformat(),
            "updated_at": admin.updated_at.isoformat(),
        },
        "token": token,
        "expires_at": expires_at.isoformat(),
    }

    return generate_response(response, 200)
