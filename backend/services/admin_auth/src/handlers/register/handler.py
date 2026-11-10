import json

from libs.core.responses import HandledError, generate_response, handle_exceptions
from libs.orm.admin_credentials import AdminCredentials
from libs.orm.admins import Admins
from libs.utils.auth import require_auth, AuthsTypes
from libs.utils.passwords import hash_password
from libs.utils.validators import password_reason, valid_email


@handle_exceptions
@require_auth(AuthsTypes.INTERNAL)
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

    if Admins.get_by_email(email):
        raise HandledError("email_taken", 409)

    admin = Admins.create(email=email, full_name=full_name)
    AdminCredentials.create(admin_id=admin.id, password_hash=hash_password(password))

    response = {
        "admin": {
            "id": admin.id,
            "email": admin.email,
            "full_name": admin.full_name,
            "created_at": admin.created_at.isoformat(),
            "updated_at": admin.updated_at.isoformat(),
        },
    }

    return generate_response(response, 201)
