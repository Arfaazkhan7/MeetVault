import os
import json

from app.core.config import settings
from app.core.runtime import IS_WORKERS


def _initialize_firebase() -> None:
    import firebase_admin
    from firebase_admin import credentials
    if firebase_admin._apps:
        return

    options = {"projectId": settings.FIREBASE_PROJECT_ID}
    if settings.FIREBASE_CREDENTIALS_PATH:
        cred_path = os.path.abspath(settings.FIREBASE_CREDENTIALS_PATH)
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, options)
    elif settings.FIREBASE_CREDENTIALS_JSON:
        cred = credentials.Certificate(json.loads(settings.FIREBASE_CREDENTIALS_JSON))
        firebase_admin.initialize_app(cred, options)
    else:
        raise RuntimeError("Firebase Admin credentials are not configured")


def verify_firebase_id_token(id_token: str) -> dict:
    if IS_WORKERS:
        return _verify_portable_firebase_token(id_token)
    from firebase_admin import auth
    _initialize_firebase()
    return auth.verify_id_token(id_token)


def _verify_portable_firebase_token(id_token: str) -> dict:
    """Verify Firebase ID tokens with Google's signing certs, without gRPC.

    Match Firebase's public-key verification requirements. No service-account
    private key is needed for signature verification. This does not check
    revocation, matching the existing verify_id_token default.
    """
    import time
    import httpx
    from jose import jwt, JWTError

    if len(id_token) > 16384:
        raise JWTError("Token too large")
    header = jwt.get_unverified_header(id_token)
    if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
        raise JWTError("Invalid Firebase token header")
    try:
        response = httpx.get(
            "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com",
            timeout=10,
        )
        response.raise_for_status()
        if len(response.content) > 65536:
            raise RuntimeError("Certificate response too large")
        certificates = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("Firebase signing certificates are temporarily unavailable") from exc
    certificate = certificates.get(header["kid"])
    if not certificate:
        raise JWTError("Unknown Firebase signing key")
    claims = jwt.decode(
        id_token, certificate, algorithms=["RS256"],
        audience=settings.FIREBASE_PROJECT_ID,
        issuer=f"https://securetoken.google.com/{settings.FIREBASE_PROJECT_ID}",
        options={"require_exp": True, "require_iat": True, "require_sub": True,
                 "require_aud": True, "require_iss": True},
    )
    now = time.time()
    subject = claims.get("sub")
    if not isinstance(subject, str) or not 1 <= len(subject) <= 128:
        raise JWTError("Invalid Firebase subject")
    if not isinstance(claims.get("iat"), (int, float)) or claims["iat"] > now:
        raise JWTError("Invalid Firebase issued-at time")
    auth_time = claims.get("auth_time")
    if not isinstance(auth_time, (int, float)) or auth_time > now:
        raise JWTError("Invalid Firebase authentication time")
    claims["uid"] = subject
    return claims

