import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

import bcrypt

from libs.core.responses import HandledError, generate_response
from libs.orm.bearer_tokens import BearerTokens
from libs.orm.users import Users

TOKEN_TTL = timedelta(hours=24)


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(user_id) -> tuple[str, datetime]:
    plain = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + TOKEN_TTL
    BearerTokens.create(user_id=user_id, token_hash=_hash(plain), expires_at=expires_at)
    return plain, expires_at


def verify_token(token: str):
    """Returns (user, bearer_token) or raises HandledError(401)."""
    if not token:
        raise HandledError("invalid_or_expired_token", 401)
    bearer = BearerTokens.get_by_hash(_hash(token))
    if bearer is None or not bearer.is_alive():
        raise HandledError("invalid_or_expired_token", 401)
    user = Users.get_by_id(bearer.user_id)
    if user is None:
        raise HandledError("invalid_or_expired_token", 401)
    return user, bearer


def require_auth(handler):
    @wraps(handler)
    def wrapper(event, context):
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        authz = headers.get("authorization", "")
        if not authz.lower().startswith("bearer "):
            return generate_response({"error": "missing_bearer_token"}, 401)
        user, bearer = verify_token(authz[7:].strip())
        event["user"] = user
        event["token"] = bearer
        return handler(event, context)
    return wrapper
