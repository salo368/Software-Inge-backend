from libs.core.responses import generate_response, handle_exceptions
from libs.utils.auth import require_auth, AuthsTypes
from libs.utils.bearer_tokens import revoke


@handle_exceptions
@require_auth(AuthsTypes.USER)
def handler(event, context):

    token = event.get("token")   

    revoke(token.id)

    response = {
        "revoked": True
    }

    return generate_response(response, 200)
