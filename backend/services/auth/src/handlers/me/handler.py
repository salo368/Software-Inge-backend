from libs.core.responses import generate_response, handle_exceptions
from libs.utils.auth import require_auth


@handle_exceptions
@require_auth
def handler(event, context):
    # Returns the authenticated user's public profile.
    # (pipeline test: single-service change should redeploy only `auth`.)
    return generate_response({"user": event["user"].public_dict()})
