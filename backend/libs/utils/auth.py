import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from libs.core.logger import Logger
from libs.core.responses import HandledError, generate_response
from libs.orm.bearer_tokens import BearerTokens
from libs.orm.users import Users

TOKEN_TTL = timedelta(hours=24)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(user_id) -> tuple[str, datetime]:
    plain = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + TOKEN_TTL
    BearerTokens.create(user_id=user_id, token_hash=_hash(plain), expires_at=expires_at)
    return plain, expires_at


def verify_token(token: str):
    """Returns (user, bearer_token) or raises HandledError(401).

    Every rejection returns the same opaque message so callers cannot probe
    which part failed, but each one logs a distinct reason.
    """
    if not token:
        raise _reject("empty token")
    bearer = BearerTokens.get_by_hash(_hash(token))
    if bearer is None:
        raise _reject("no row for hash")
    if bearer.revoked_at is not None:
        raise _reject("token revoked")
    if not bearer.is_alive():
        raise _reject(f"token expired at {bearer.expires_at}")
    user = Users.get_by_id(bearer.user_id)
    if user is None:
        raise _reject(f"no user {bearer.user_id}")
    return user, bearer


def _reject(reason: str) -> HandledError:
    Logger.log("WARNING", f"verify_token rejected: {reason}")
    return HandledError("invalid_or_expired_token", 401)


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
