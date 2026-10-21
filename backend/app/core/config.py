from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import json

# Known insecure defaults, placeholders, and weak patterns rejected in production
INSECURE_OR_PLACEHOLDER_SECRETS = {
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
    "default",
    "admin",
    "12345678",
    "1234567890",
    "replace_with_at_least_32_random_bytes_in_production",
}

ALLOWED_JWT_ALGORITHMS = {"HS256", "HS384", "HS512"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    PROJECT_NAME: str = "MeetVault"
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/meetingdb"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    AI_WORKER_QUEUE: str = "database"
    AI_WORKER_POLL_INTERVAL_SECONDS: float = 5.0
    CLOUDFLARE_AI_QUEUE_URL: str = ""
    CLOUDFLARE_AI_QUEUE_SECRET: str = ""
    CLOUDFLARE_AI_CALLBACK_SECRET: str = ""

    # JWT
    JWT_SECRET: str = "dev-insecure-secret-for-local-testing-only-do-not-use-in-production-32bytes"
    JWT_PREVIOUS_SECRETS: str = ""  # Comma-separated or JSON list of rotated secrets still valid for decoding
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "meetvault-api"
    JWT_AUDIENCE: str = "meetvault-client"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours — client implements refresh; short expiry caused 401 errors
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    @property
    def previous_secrets(self) -> list[str]:
        raw = self.JWT_PREVIOUS_SECRETS.strip()
        if not raw:
            return []
        if raw.startswith("[") and raw.endswith("]"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(s).strip() for s in parsed if str(s).strip()]
            except json.JSONDecodeError:
                pass
        return [s.strip() for s in raw.split(",") if s.strip()]

    # App
    ENVIRONMENT: str = "development"
    BACKEND_CORS_ORIGINS: str = ""
    API_BASE_URL: str = "http://localhost:8000/api/v1"
    FRONTEND_PUBLIC_URL: str = "http://localhost:3000"
    FIREBASE_PROJECT_ID: str = "ai-meet-f8fd0"
    FIREBASE_CREDENTIALS_PATH: str = ""
    FIREBASE_CREDENTIALS_JSON: str = ""

    @property
    def cors_origins(self) -> list[str]:
        if self.ENVIRONMENT == "development":
            return ["*"]
        raw_origins = self.BACKEND_CORS_ORIGINS.strip()
        if not raw_origins:
            return []

        try:
            parsed = json.loads(raw_origins)
            if isinstance(parsed, list):
                return [str(origin).strip().strip('"').strip("'") for origin in parsed if str(origin).strip()]
        except json.JSONDecodeError:
            pass

        return [
            origin.strip().strip("[]").strip().strip('"').strip("'")
            for origin in raw_origins.split(",")
            if origin.strip().strip("[]").strip().strip('"').strip("'")
        ]

    # LiveKit
    LIVEKIT_URL: str = "wss://your-livekit-url"
    LIVEKIT_API_KEY: str = "your_livekit_api_key"
    LIVEKIT_API_SECRET: str = "your_livekit_api_secret"
    LIVEKIT_TOKEN_EXPIRE_MINUTES: int = 120

    # Private recording storage
    STORAGE_BACKEND: str = "supabase"
    SUPABASE_URL: str = "https://your-project.supabase.co"
    SUPABASE_SERVICE_ROLE_KEY: str = "your_supabase_service_role_key"
    SUPABASE_STORAGE_BUCKET: str = "meeting-recordings"
    RECORDING_SIGNED_URL_EXPIRE_SECONDS: int = 900
    MAX_RECORDING_UPLOAD_BYTES: int = 500 * 1024 * 1024
    AUDIO_TEMP_DIR: Optional[str] = None
    AUDIO_TEMP_MAX_AGE_MINUTES: int = 30

    # AWS
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET: str = ""

    # LLM / RAG
    LLM_PROVIDER: str = "mock"           # "mock" | "openai"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_API_KEY: str = ""
    EMBEDDING_MODEL: str = ""
    OPENAI_API_KEY: Optional[str] = None
    RAG_TOP_K: int = 12                  # Max evidence items sent to LLM
    RAG_MIN_SCORE: float = 0.15          # Min similarity score to include evidence

    @field_validator(
        "DATABASE_URL",
        "BACKEND_CORS_ORIGINS",
        "API_BASE_URL",
        "FRONTEND_PUBLIC_URL",
        "FIREBASE_PROJECT_ID",
        "FIREBASE_CREDENTIALS_PATH",
        "FIREBASE_CREDENTIALS_JSON",
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "STORAGE_BACKEND",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_STORAGE_BUCKET",
        "AUDIO_TEMP_DIR",
        "LLM_PROVIDER",
        "LLM_MODEL",
        "LLM_API_KEY",
        "EMBEDDING_MODEL",
        "OPENAI_API_KEY",
        "AI_WORKER_QUEUE",
        "CLOUDFLARE_AI_QUEUE_URL",
        "CLOUDFLARE_AI_QUEUE_SECRET",
        "CLOUDFLARE_AI_CALLBACK_SECRET",
        "JWT_SECRET",
        "JWT_PREVIOUS_SECRETS",
        "JWT_ALGORITHM",
        "JWT_ISSUER",
        "JWT_AUDIENCE",
        mode="before",
    )
    @classmethod
    def strip_env_strings(cls, value):
        if isinstance(value, str):
            return value.strip().strip('"').strip("'").strip()
        return value

    def validate_production_security(self) -> None:
        """Validate production security requirements.
        Raises ValueError with a clear, diagnostic message if security invariants are violated.
        """
        alg = (self.JWT_ALGORITHM or "").strip().upper()
        if not alg or alg not in ALLOWED_JWT_ALGORITHMS:
            raise ValueError(
                f"Invalid JWT_ALGORITHM '{self.JWT_ALGORITHM}'. "
                f"Supported algorithms: {sorted(ALLOWED_JWT_ALGORITHMS)}. Algorithm 'none' is strictly forbidden."
            )

        is_production = self.ENVIRONMENT.lower() in ("production", "prod", "staging")
        if not is_production:
            return

        secret = (self.JWT_SECRET or "").strip()
        if not secret:
            raise ValueError(
                "Production configuration error: JWT_SECRET must not be empty. "
                "Provide a strong random secret with at least 32 characters."
            )

        if secret.lower() in {s.lower() for s in INSECURE_OR_PLACEHOLDER_SECRETS}:
            raise ValueError(
                "Production configuration error: JWT_SECRET is set to an insecure default or placeholder value. "
                "Generate a cryptographically secure random key (e.g. `openssl rand -hex 32`)."
            )

        if any(kw in secret.lower() for kw in ("change-this", "changeme", "your_secret", "replace_with", "example", "placeholder")):
            raise ValueError(
                "Production configuration error: JWT_SECRET appears to contain a placeholder phrase. "
                "Set a real random production secret."
            )

        if len(secret) < 32:
            raise ValueError(
                f"Production configuration error: JWT_SECRET is too short ({len(secret)} characters). "
                f"Production secrets must be at least 32 characters for {alg}."
            )

        if len(set(secret)) < 8:
            raise ValueError(
                "Production configuration error: JWT_SECRET has insufficient entropy (too few distinct characters)."
            )

        # Validate previous secrets if provided in production
        for prev in self.previous_secrets:
            if prev.lower() in {s.lower() for s in INSECURE_OR_PLACEHOLDER_SECRETS}:
                raise ValueError(
                    "Production configuration error: JWT_PREVIOUS_SECRETS contains a known insecure default or placeholder."
                )
            if len(prev) < 32:
                raise ValueError(
                    f"Production configuration error: Previous secret '{prev[:4]}...' is too short (< 32 chars)."
                )

    @model_validator(mode="after")
    def validate_security_configuration(self):
        self.validate_production_security()
        return self


settings = Settings()
