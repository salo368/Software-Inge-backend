from datetime import datetime, timezone

from libs.orm.user_bearer_tokens import UserBearerTokens


def is_alive(bearer) -> bool:

    is_alive = bearer.revoked_at is None and bearer.expires_at > datetime.now(timezone.utc)

    return is_alive


def revoke(token_id) -> bool:

    updated = UserBearerTokens.update_by_id(token_id, {"revoked_at": datetime.now(timezone.utc)})

    return updated is not None
