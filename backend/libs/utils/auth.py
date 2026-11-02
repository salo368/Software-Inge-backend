import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from libs.core.logger import Logger
from libs.core.responses import HandledError, generate_response
from libs.orm.bearer_tokens import BearerTokens
from libs.orm.users import Users
from libs.utils.bearer_tokens import is_alive

TOKEN_DURATION_HOURS = 24

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(user_id) -> tuple[str, datetime]:

    plain = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=TOKEN_DURATION_HOURS)

    BearerTokens.create(
        user_id=user_id,
        token_hash=_hash(plain),
        expires_at=expires_at,
    )

    return plain, expires_at



def require_auth(handler):
    @wraps(handler)
    def wrapper(event, context):

        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

        authz = headers.get("authorization", "")

        if not authz.lower().startswith("bearer "):
            Logger.log("WARNING", f"Missing or invalid Authorization header: {authz}")
            raise HandledError("missing_bearer_token", 401)

        token = authz[7:].strip()
        
        if not token:
            Logger.log("WARNING", f"No token provided")
            raise HandledError("invalid_or_expired_token", 401)
            
        bearer = BearerTokens.get_by_hash(_hash(token))
        if bearer is None:
            Logger.log("WARNING", f"Token not found: {token}")
            raise HandledError("invalid_or_expired_token", 401)
        
        if bearer.revoked_at is not None:
            Logger.log("WARNING", f"Token revoked: {token}")
            raise HandledError("invalid_or_expired_token", 401)
    
        if not is_alive(bearer):
            Logger.log("WARNING", f"Token expired: {token}")
            raise HandledError("invalid_or_expired_token", 401)
    
        user = Users.get_by_id(bearer.user_id)
        if user is None:
            Logger.log("WARNING", f"User not found: {bearer.user_id}")
            raise HandledError("invalid_or_expired_token", 401)

        event["user"] = user
        event["token"] = bearer

        return handler(event, context)
    
    return wrapper
