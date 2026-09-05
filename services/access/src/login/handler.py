from utils.auth.passwords import verify_password
from utils.auth.tokens import issue_token
from utils.http import err, ok, parse_body
from utils.orm.models import Users


def login(event, context):
    body = parse_body(event)
    if body is None:
        return err(400, "invalid_json")

    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not username or not password:
        return err(400, "missing_fields")

    user = Users.get_by_username(username=username)
    if user is None or not verify_password(password, user.password_hash):
        return err(401, "invalid_credentials")

    token, expires_at = issue_token(user_id=user.id)

    return ok(200, {
        "token": token,
        "expires_at": expires_at,
        "user": {
            "id": user.id,
            "username": user.username,
            "name": user.name,
        },
    })
