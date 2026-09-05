from utils.auth.passwords import hash_password
from utils.http import err, ok, parse_body
from utils.orm.models import Users


def register(event, context):
    body = parse_body(event)
    if body is None:
        return err(400, "invalid_json")

    username = (body.get("username") or "").strip()
    name = (body.get("name") or "").strip()
    password = body.get("password") or ""

    if not username or not name or not password:
        return err(400, "missing_fields", "username, name, password son requeridos")

    if len(password) < 8:
        return err(400, "password_too_short", "minimo 8 caracteres")

    if Users.get_by_username(username=username) is not None:
        return err(409, "username_taken")

    user = Users.create(
        username=username,
        name=name,
        password_hash=hash_password(password),
    )

    return ok(201, {
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "created_at": user.created_at,
    })
