from datetime import datetime, timezone
from enum import Enum

from libs.orm.admin_bearer_tokens import AdminBearerTokens
from libs.orm.user_bearer_tokens import UserBearerTokens


class AuthsTypes(str, Enum):
    USER = "USER"
    INTERNAL = "INTERNAL"


def is_alive(bearer) -> bool:

    is_alive = bearer.revoked_at is None and bearer.expires_at > datetime.now(timezone.utc)

    return is_alive


def revoke(token_id, auth_type: AuthsTypes) -> bool:

    tokens = AdminBearerTokens if auth_type is AuthsTypes.INTERNAL else UserBearerTokens

    updated = tokens.update_by_id(token_id, {"revoked_at": datetime.now(timezone.utc)})

    return updated is not None
