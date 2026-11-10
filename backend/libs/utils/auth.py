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


def _extract_token(event) -> str:

    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

    authz = headers.get("authorization", "")

    if not authz.lower().startswith("bearer "):
        Logger.log("WARNING", f"Missing or invalid Authorization header: {authz}")
        raise HandledError("missing_bearer_token", 401)

    token = authz[7:].strip()

    if not token:
        Logger.log("WARNING", f"No token provided")
        raise HandledError("invalid_or_expired_token", 401)

    return token


def _resolve(token: str, auth_type: AuthsTypes):
    """(event key, subject, bearer) when `token` is a live token of `auth_type`,
    otherwise the failure reason as a string. Never logs or raises, so a
    caller can probe more than one type without noise."""

    tokens, subjects, subject_column, event_key = _auth_tables(auth_type)

    bearer = tokens.get_by_hash(_hash(token))
    if bearer is None:
        return "token not found"

    if bearer.revoked_at is not None:
        return "token revoked"

    if not is_alive(bearer):
        return "token expired"

    subject_id = getattr(bearer, subject_column)
    subject = subjects.get_by_id(subject_id)
    if subject is None:
        return f"subject not found: {subject_id}"

    return event_key, subject, bearer


def require_auth(auth_type: AuthsTypes):

    if not isinstance(auth_type, AuthsTypes):
        raise TypeError("require_auth needs an explicit type: use @require_auth(AuthsTypes.USER)")

    def decorator(handler):
        @wraps(handler)
        def wrapper(event, context):

            token = _extract_token(event)

            resolved = _resolve(token, auth_type)
            if isinstance(resolved, str):
                Logger.log("WARNING", f"Auth failed for {auth_type.value}: {resolved}")
                raise HandledError("invalid_or_expired_token", 401)

            event_key, subject, bearer = resolved
            event[event_key] = subject
            event["token"] = bearer

            return handler(event, context)

        return wrapper

    return decorator


def require_any_auth(handler):
    """Accepts a user token or an admin (internal) token, for endpoints that
    serve both. The subject lands in `event["user"]` or `event["admin"]`
    (never both), so the handler branches on which key is present."""

    @wraps(handler)
    def wrapper(event, context):

        token = _extract_token(event)

        failures = []
        for auth_type in (AuthsTypes.USER, AuthsTypes.INTERNAL):
            resolved = _resolve(token, auth_type)
            if not isinstance(resolved, str):
                event_key, subject, bearer = resolved
                event[event_key] = subject
                event["token"] = bearer
                return handler(event, context)
            failures.append(f"{auth_type.value}: {resolved}")

        Logger.log("WARNING", f"Auth failed ({'; '.join(failures)})")
        raise HandledError("invalid_or_expired_token", 401)

    return wrapper
