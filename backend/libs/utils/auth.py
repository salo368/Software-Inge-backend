import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from libs.core.logger import Logger
from libs.core.responses import HandledError, generate_response
from libs.orm.admin_bearer_tokens import AdminBearerTokens
from libs.orm.admins import Admins
from libs.orm.user_bearer_tokens import UserBearerTokens
from libs.orm.users import Users
from libs.utils.bearer_tokens import AuthsTypes, is_alive

TOKEN_DURATION_HOURS = 24


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _auth_tables(auth_type: AuthsTypes):
    """(tokens table, subjects table, token column holding the subject id,
    event key the subject is stored under). Resolved on every call so tests
    can monkeypatch the module-level tables."""
    if auth_type is AuthsTypes.INTERNAL:
        return AdminBearerTokens, Admins, "admin_id", "admin"
    return UserBearerTokens, Users, "user_id", "user"


def issue_token(subject_id, auth_type: AuthsTypes) -> tuple[str, datetime]:

    tokens, _, _, _ = _auth_tables(auth_type)

    plain = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=TOKEN_DURATION_HOURS)

    tokens.create(subject_id, _hash(plain), expires_at)

    return plain, expires_at


def require_auth(auth_type: AuthsTypes):

    if not isinstance(auth_type, AuthsTypes):
        raise TypeError("require_auth needs an explicit type: use @require_auth(AuthsTypes.USER)")

    def decorator(handler):
        @wraps(handler)
        def wrapper(event, context):

            tokens, subjects, subject_column, event_key = _auth_tables(auth_type)

            headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

            authz = headers.get("authorization", "")

            if not authz.lower().startswith("bearer "):
                Logger.log("WARNING", f"Missing or invalid Authorization header: {authz}")
                raise HandledError("missing_bearer_token", 401)

            token = authz[7:].strip()

            if not token:
                Logger.log("WARNING", f"No token provided")
                raise HandledError("invalid_or_expired_token", 401)

            bearer = tokens.get_by_hash(_hash(token))
            if bearer is None:
                Logger.log("WARNING", f"Token not found for {auth_type.value}: {token}")
                raise HandledError("invalid_or_expired_token", 401)

            if bearer.revoked_at is not None:
                Logger.log("WARNING", f"Token revoked: {token}")
                raise HandledError("invalid_or_expired_token", 401)

            if not is_alive(bearer):
                Logger.log("WARNING", f"Token expired: {token}")
                raise HandledError("invalid_or_expired_token", 401)

            subject_id = getattr(bearer, subject_column)
            subject = subjects.get_by_id(subject_id)
            if subject is None:
                Logger.log("WARNING", f"{auth_type.value} not found: {subject_id}")
                raise HandledError("invalid_or_expired_token", 401)

            event[event_key] = subject
            event["token"] = bearer

            return handler(event, context)

        return wrapper

    return decorator
