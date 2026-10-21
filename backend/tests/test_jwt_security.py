"""
MEETVAULT — Comprehensive JWT Secret and Security Configuration Tests
Tests:
- Missing, empty, placeholder, weak, and low-entropy JWT secrets in production mode
- Valid production configuration vs development/test defaults
- Algorithm validation, mismatch rejection, and strict rejection of 'none' algorithm
- Token expiration, invalid signatures, malformed tokens
- Required claims enforcement (sub, type, exp)
- Issuer (iss) and Audience (aud) claim verification
- Secret rotation support via JWT_PREVIOUS_SECRETS
- Revocation of compromised secrets
- Development bypass lockdown in production mode
- Startup failure on misconfiguration
"""
import base64
import json
import pytest
from datetime import datetime, timedelta, timezone
from jose import jwt

from app.core.config import Settings
from app.core.tokens import create_token, decode_token, JWTError
from app.core.dependencies import get_current_user
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials


# Helper to build raw tokens with custom headers/payloads
def _make_raw_token(header: dict, payload: dict, secret: str = "dev-insecure-secret-for-local-testing-only-do-not-use-in-production-32bytes") -> str:
    def _b64(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode("utf-8")).decode("utf-8").rstrip("=")
    
    encoded_header = _b64(header)
    encoded_payload = _b64(payload)
    if header.get("alg", "").lower() == "none":
        return f"{encoded_header}.{encoded_payload}."
    
    token = jwt.encode(payload, secret, algorithm=header.get("alg", "HS256"), headers=header)
    return token if isinstance(token, str) else token.decode("utf-8")


class TestProductionSecretValidation:
    """Validate that production configuration strictly enforces security requirements."""

    def test_production_rejects_empty_secret(self):
        with pytest.raises(ValueError, match="JWT_SECRET must not be empty"):
            Settings(ENVIRONMENT="production", JWT_SECRET="")

    def test_production_rejects_whitespace_secret(self):
        with pytest.raises(ValueError, match="JWT_SECRET must not be empty"):
            Settings(ENVIRONMENT="production", JWT_SECRET="   ")

    @pytest.mark.parametrize("insecure_secret", [
        "change-this-to-a-very-long-random-secret-in-production",
        "your_jwt_secret",
        "your-jwt-secret",
        "change_me",
        "changeme",
        "secret",
        "secretkey",
        "jwt_secret",
        "jwt-secret",
        "password",
        "dev-insecure-secret-for-local-testing-only-do-not-use-in-production-32bytes",
        "replace_with_at_least_32_random_bytes_in_production",
    ])
    def test_production_rejects_known_defaults_and_placeholders(self, insecure_secret):
        with pytest.raises(ValueError, match="insecure default or placeholder"):
            Settings(ENVIRONMENT="production", JWT_SECRET=insecure_secret)

    def test_production_rejects_short_secret(self):
        with pytest.raises(ValueError, match="too short"):
            Settings(ENVIRONMENT="production", JWT_SECRET="short-secret-under-32-chars!")

    def test_production_rejects_placeholder_phrase(self):
        with pytest.raises(ValueError, match="placeholder phrase"):
            Settings(ENVIRONMENT="production", JWT_SECRET="my-super-long-changeme-key-that-is-over-32-characters!")

    def test_production_rejects_low_entropy_secret(self):
        with pytest.raises(ValueError, match="insufficient entropy"):
            Settings(ENVIRONMENT="production", JWT_SECRET="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")

    def test_production_accepts_strong_secret(self):
        # 64 character hex string (32 bytes)
        strong_secret = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
        s = Settings(ENVIRONMENT="production", JWT_SECRET=strong_secret)
        assert s.JWT_SECRET == strong_secret

    def test_development_accepts_default_configuration(self):
        s = Settings(ENVIRONMENT="development")
        assert len(s.JWT_SECRET) >= 32
        # Should not raise in development

    def test_staging_enforces_production_rules(self):
        with pytest.raises(ValueError, match="insecure default or placeholder"):
            Settings(ENVIRONMENT="staging", JWT_SECRET="change_me")


class TestAlgorithmValidation:
    """Validate algorithm enforcement and rejection of unsafe algorithms."""

    def test_rejects_none_algorithm_in_config(self):
        with pytest.raises(ValueError, match="Supported algorithms"):
            Settings(JWT_ALGORITHM="none")

    def test_rejects_unsupported_algorithm_in_config(self):
        with pytest.raises(ValueError, match="Supported algorithms"):
            Settings(JWT_ALGORITHM="DES")

    def test_decode_rejects_none_algorithm_in_token_header(self, monkeypatch):
        none_token = _make_raw_token(
            header={"alg": "none", "typ": "JWT"},
            payload={"sub": "USR-test", "type": "access", "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()}
        )
        with pytest.raises(JWTError, match="Algorithm 'none' is strictly rejected"):
            decode_token(none_token)

    def test_decode_rejects_algorithm_mismatch(self):
        # Create token with HS512 when system is configured for HS256
        token = jwt.encode(
            {"sub": "USR-test", "type": "access", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            "dev-insecure-secret-for-local-testing-only-do-not-use-in-production-32bytes",
            algorithm="HS512"
        )
        with pytest.raises(JWTError, match="does not match expected algorithm"):
            decode_token(token)


class TestTokenIntegrityAndClaims:
    """Validate signature integrity, expiration, and required claim enforcement."""

    def test_valid_token_decodes_successfully(self):
        token = create_token(subject="USR-0001", token_type="access")
        payload = decode_token(token)
        assert payload["sub"] == "USR-0001"
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "iat" in payload
        assert "iss" in payload
        assert "aud" in payload

    def test_expired_token_is_rejected(self):
        expired_token = jwt.encode(
            {
                "sub": "USR-0001",
                "type": "access",
                "exp": datetime.now(timezone.utc) - timedelta(minutes=10),
                "iss": "meetvault-api",
                "aud": "meetvault-client",
            },
            "dev-insecure-secret-for-local-testing-only-do-not-use-in-production-32bytes",
            algorithm="HS256",
        )
        with pytest.raises(JWTError, match="expired"):
            decode_token(expired_token)

    def test_invalid_signature_is_rejected(self):
        token = jwt.encode(
            {
                "sub": "USR-0001",
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
                "iss": "meetvault-api",
                "aud": "meetvault-client",
            },
            "wrong-secret-key-that-does-not-match-current-or-previous",
            algorithm="HS256",
        )
        with pytest.raises(JWTError, match="verification failed"):
            decode_token(token)

    def test_malformed_token_string_is_rejected(self):
        with pytest.raises(JWTError):
            decode_token("not.a.valid.jwt.token")

    def test_empty_token_is_rejected(self):
        with pytest.raises(JWTError, match="Token is empty"):
            decode_token("")

    def test_missing_sub_claim_is_rejected(self):
        token = jwt.encode(
            {
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
                "iss": "meetvault-api",
                "aud": "meetvault-client",
            },
            "dev-insecure-secret-for-local-testing-only-do-not-use-in-production-32bytes",
            algorithm="HS256",
        )
        with pytest.raises(JWTError, match="Missing or empty token subject"):
            decode_token(token)

    def test_invalid_token_type_claim_is_rejected(self):
        token = jwt.encode(
            {
                "sub": "USR-0001",
                "type": "admin_super_token",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
                "iss": "meetvault-api",
                "aud": "meetvault-client",
            },
            "dev-insecure-secret-for-local-testing-only-do-not-use-in-production-32bytes",
            algorithm="HS256",
        )
        with pytest.raises(JWTError, match="Invalid or missing token type claim"):
            decode_token(token)

    def test_mismatched_issuer_is_rejected(self):
        token = jwt.encode(
            {
                "sub": "USR-0001",
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
                "iss": "untrusted-external-issuer",
                "aud": "meetvault-client",
            },
            "dev-insecure-secret-for-local-testing-only-do-not-use-in-production-32bytes",
            algorithm="HS256",
        )
        with pytest.raises(JWTError):
            decode_token(token)

    def test_mismatched_audience_is_rejected(self):
        token = jwt.encode(
            {
                "sub": "USR-0001",
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
                "iss": "meetvault-api",
                "aud": "wrong-audience",
            },
            "dev-insecure-secret-for-local-testing-only-do-not-use-in-production-32bytes",
            algorithm="HS256",
        )
        with pytest.raises(JWTError):
            decode_token(token)


class TestSecretRotation:
    """Validate zero-downtime key rotation and emergency revocation."""

    def test_rotated_previous_secret_decodes_successfully(self, monkeypatch):
        old_secret = "old-production-secret-at-least-32-chars-long-1"
        new_secret = "new-production-secret-at-least-32-chars-long-2"

        # Token created under old secret
        token = jwt.encode(
            {
                "sub": "USR-0001",
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
                "iss": "meetvault-api",
                "aud": "meetvault-client",
            },
            old_secret,
            algorithm="HS256",
        )

        from app.core import config
        monkeypatch.setattr(config.settings, "JWT_SECRET", new_secret)
        monkeypatch.setattr(config.settings, "JWT_PREVIOUS_SECRETS", old_secret)

        payload = decode_token(token)
        assert payload["sub"] == "USR-0001"

    def test_compromised_secret_revocation_invalidates_immediately(self, monkeypatch):
        compromised_secret = "compromised-secret-at-least-32-chars-long!"
        fresh_secret = "fresh-replacement-secret-at-least-32-chars!"

        token = jwt.encode(
            {
                "sub": "USR-victim",
                "type": "access",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
                "iss": "meetvault-api",
                "aud": "meetvault-client",
            },
            compromised_secret,
            algorithm="HS256",
        )

        from app.core import config
        # Compromised secret is removed from both JWT_SECRET and JWT_PREVIOUS_SECRETS
        monkeypatch.setattr(config.settings, "JWT_SECRET", fresh_secret)
        monkeypatch.setattr(config.settings, "JWT_PREVIOUS_SECRETS", "")

        with pytest.raises(JWTError, match="verification failed"):
            decode_token(token)


class TestEnvironmentBypassLockdown:
    """Validate that development bypass tokens are strictly forbidden in production."""

    def test_dev_bypass_disabled_in_production(self, monkeypatch):
        from app.core import config
        monkeypatch.setattr(config.settings, "ENVIRONMENT", "production")

        creds = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="mv-local-token:admin@example.com"
        )
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(credentials=creds, db=None)
        assert exc_info.value.status_code == 401

    def test_mail_bypass_disabled_in_staging(self, monkeypatch):
        from app.core import config
        monkeypatch.setattr(config.settings, "ENVIRONMENT", "staging")

        creds = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="mail-attacker@example.com"
        )
        with pytest.raises(HTTPException) as exc_info:
            get_current_user(credentials=creds, db=None)
        assert exc_info.value.status_code == 401


class TestStartupFailureVerification:
    """Validate startup fails fast when security requirements are violated."""

    def test_startup_lifespan_aborts_on_insecure_production_secret(self, monkeypatch):
        from app.core import config
        monkeypatch.setattr(config.settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(config.settings, "JWT_SECRET", "weak-secret")

        from app.main import lifespan, app
        import asyncio

        async def run_startup():
            async with lifespan(app):
                pass

        with pytest.raises(RuntimeError, match="Startup aborted due to production security configuration error"):
            asyncio.run(run_startup())
