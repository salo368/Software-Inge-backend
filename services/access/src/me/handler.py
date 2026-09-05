from utils.auth.middleware import require_auth
from utils.http import ok


@require_auth
def me(event, context):
    user = event["auth"].user
    return ok(200, {
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "created_at": user.created_at,
    })
