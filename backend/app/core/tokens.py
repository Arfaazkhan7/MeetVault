from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from jose import JWTError, jwt

from app.core.config import settings

# ── Token types ────────────────────────────────────────────────────────────────
TokenType = Literal["access", "refresh"]


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def create_token(
    subject: str,
    token_type: TokenType,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """
    Create a signed JWT.

    - access tokens expire in ACCESS_TOKEN_EXPIRE_MINUTES
    - refresh tokens expire in REFRESH_TOKEN_EXPIRE_DAYS
    """
    if token_type == "access":
        expire = _now() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    else:
        expire = _now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    payload: dict[str, Any] = {
        "sub": subject,          # subject = user public_id (e.g. USR-0001)
        "type": token_type,
        "exp": expire,
        "iat": _now(),
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT.
    Raises jose.JWTError on failure — callers must handle it.
    """
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
    )
