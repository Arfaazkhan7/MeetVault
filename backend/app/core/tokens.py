from datetime import datetime, timedelta, timezone
from typing import Any, Literal
import logging

try:
    from jose import JWTError, jwt
    from jose.exceptions import ExpiredSignatureError, JWTClaimsError
except ImportError:
    try:
        import jwt
        from jwt.exceptions import (
            PyJWTError as JWTError,
            ExpiredSignatureError,
            InvalidTokenError as JWTClaimsError,
        )
    except ImportError:
        class JWTError(Exception):
            pass
        class ExpiredSignatureError(JWTError):
            pass
        class JWTClaimsError(JWTError):
            pass
        jwt = None

from app.core.config import settings

logger = logging.getLogger(__name__)

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
    - embeds issuer and audience if configured
    - embeds iat, nbf, and exp claims
    """
    if jwt is None:
        raise RuntimeError("No JWT library available (install python-jose[cryptography] or PyJWT)")

    if not subject or not str(subject).strip():
        raise ValueError("Subject ('sub') cannot be empty")

    if token_type not in ("access", "refresh"):
        raise ValueError(f"Invalid token_type: {token_type}")

    now = _now()
    if token_type == "access":
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    else:
        expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    payload: dict[str, Any] = {
        "sub": str(subject).strip(),          # subject = user public_id (e.g. USR-0001)
        "type": token_type,
        "exp": expire,
        "iat": now,
        "nbf": now - timedelta(seconds=5),   # 5-second leeway for slight clock skew
    }
    if settings.JWT_ISSUER:
        payload["iss"] = settings.JWT_ISSUER
    if settings.JWT_AUDIENCE:
        payload["aud"] = settings.JWT_AUDIENCE

    if extra_claims:
        payload.update(extra_claims)

    encoded = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded if isinstance(encoded, str) else encoded.decode("utf-8")


def decode_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT.

    Validates:
    - Token format and header structure
    - Algorithm strictly matches settings.JWT_ALGORITHM (rejects 'none' and algorithm switching)
    - Signature matches settings.JWT_SECRET or an active previous secret (graceful rotation)
    - Expiration (exp), not-before (nbf), issued-at (iat)
    - Issuer (iss) and audience (aud) claims if configured
    - Required claims: 'sub' (non-empty subject) and 'type' ('access' or 'refresh')

    Raises JWTError on failure — callers must handle it and never grant access on failure.
    """
    if jwt is None:
        raise RuntimeError("No JWT library available (install python-jose[cryptography] or PyJWT)")

    if token is None or not isinstance(token, str):
        raise JWTError("Token is missing or not a string")

    token = token.strip()
    if not token:
        raise JWTError("Token is empty")

    # 1. Inspect unverified header for algorithm verification
    try:
        header = jwt.get_unverified_header(token)
    except Exception as exc:
        raise JWTError(f"Malformed token header: {exc}") from exc

    if not isinstance(header, dict):
        raise JWTError("Malformed token header: header must be a JSON object")

    token_alg = header.get("alg")
    if not token_alg:
        raise JWTError("Missing 'alg' in token header")

    if str(token_alg).lower() == "none":
        raise JWTError("Algorithm 'none' is strictly rejected")

    if str(token_alg).upper() != settings.JWT_ALGORITHM.upper():
        raise JWTError(
            f"Algorithm '{token_alg}' does not match expected algorithm '{settings.JWT_ALGORITHM}'"
        )

    # 2. Multi-secret verification (primary secret first, followed by previous rotated secrets)
    candidate_secrets = [settings.JWT_SECRET]
    for s in settings.previous_secrets:
        if s and s not in candidate_secrets:
            candidate_secrets.append(s)

    decoded: dict[str, Any] | None = None
    last_exc: Exception | None = None

    for secret in candidate_secrets:
        try:
            decode_kwargs: dict[str, Any] = {
                "algorithms": [settings.JWT_ALGORITHM],
            }
            if settings.JWT_ISSUER:
                decode_kwargs["issuer"] = settings.JWT_ISSUER
            if settings.JWT_AUDIENCE:
                decode_kwargs["audience"] = settings.JWT_AUDIENCE

            decoded = jwt.decode(token, secret, **decode_kwargs)
            break
        except ExpiredSignatureError as exc:
            # Token signature matched but has expired — abort immediately
            raise JWTError("Token signature has expired") from exc
        except Exception as exc:
            last_exc = exc
            continue

    if decoded is None:
        if isinstance(last_exc, JWTError):
            raise last_exc
        raise JWTError(f"Token verification failed: {last_exc}") from last_exc

    # 3. Claims validation
    sub = decoded.get("sub")
    if not sub or not str(sub).strip():
        raise JWTError("Missing or empty token subject ('sub') claim")

    token_type = decoded.get("type")
    if token_type not in ("access", "refresh"):
        raise JWTError(f"Invalid or missing token type claim: '{token_type}'")

    if "exp" not in decoded:
        raise JWTError("Missing token expiration ('exp') claim")

    return decoded
