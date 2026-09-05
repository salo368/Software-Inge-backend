from utils.auth.middleware import require_auth
from utils.auth.tokens import revoke_token
from utils.http import ok


@require_auth
def logout(event, context):
    revoke_token(bearer_id=event["auth"].token.id)
    return ok(200, {"status": "logged_out"})
