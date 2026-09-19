from libs.core.responses import generate_response, handle_exceptions
from libs.orm.bearer_tokens import BearerTokens
from libs.utils.auth import require_auth


@handle_exceptions
@require_auth
def handler(event, context):
    BearerTokens.revoke(event["token"].id)
    return generate_response({"revoked": True})
