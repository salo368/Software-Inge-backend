"""Decorador @require_auth para proteger handlers Lambda.

Uso:
    from utils.auth.middleware import require_auth

    @require_auth
    def sign(event, context):
        user = event["auth"].user
        token = event["auth"].token
        return {"statusCode": 200, ...}

Que hace:
    1. Lee header 'Authorization: Bearer <token>'.
    2. Valida el token (hash, existencia, no revocado, no expirado).
    3. Si valido: inyecta event['auth'] = AuthContext(user, token) y llama al handler.
    4. Si invalido: retorna 401 sin llamar al handler.
"""
import json
from functools import wraps

from utils.auth.tokens import verify_token


def require_auth(handler):
    @wraps(handler)
    def wrapper(event, context):
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        authz = headers.get("authorization", "")

        if not authz.lower().startswith("bearer "):
            return _err(401, "missing_bearer_token")

        token = authz[7:].strip()
        auth = verify_token(token)
        if auth is None:
            return _err(401, "invalid_or_expired_token")

        event["auth"] = auth
        return handler(event, context)

    return wrapper


def _err(status: int, code: str) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": code}),
    }
