"""Emision y verificacion de bearer tokens.

- El token plano NUNCA se guarda: solo SHA256(token) en bearer_tokens.token_hash.
- Verificacion: se recalcula SHA256 del token entrante y se busca en DB.
- TTL default: 24 horas.
"""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from utils.orm.models import BearerTokens, Users


TOKEN_TTL = timedelta(hours=24)


@dataclass
class AuthContext:
    user: Users
    token: BearerTokens


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(user_id: int, ttl: timedelta = TOKEN_TTL) -> tuple[str, datetime]:
    """Genera token nuevo, guarda su hash en DB, devuelve (token_plano, expires_at)."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + ttl

    BearerTokens.create(
        user_id=user_id,
        token_hash=_hash(token),
        expires_at=expires_at,
    )
    return token, expires_at


def verify_token(token: str) -> AuthContext | None:
    """Retorna AuthContext si el token es valido, None si no."""
    if not token:
        return None

    bearer = BearerTokens.get_by_token_hash(token_hash=_hash(token))
    if bearer is None:
        return None
    if bearer.revoked_at is not None:
        return None
    if bearer.expires_at < datetime.now(timezone.utc):
        return None

    user = Users.get_by_id(id=bearer.user_id)
    if user is None:
        return None

    return AuthContext(user=user, token=bearer)


def revoke_token(bearer_id: int) -> bool:
    result = BearerTokens.update_by_id(
        id=bearer_id,
        data={"revoked_at": datetime.now(timezone.utc)},
    )
    return result is not None
