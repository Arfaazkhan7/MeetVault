from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import json
from app.core.runtime import IS_WORKERS


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
    JWT_SECRET: str = "change-this-to-a-very-long-random-secret-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours — client implements refresh; short expiry caused 401 errors
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

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
    DOCUMENT_STORAGE_BACKEND: str = "local"
    SUPABASE_DOCUMENTS_BUCKET: str = "meeting-documents"
    PASSWORD_HASH_SCHEMA: str = "extensions"

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
        "LLM_PROVIDER",
        "LLM_MODEL",
        "LLM_API_KEY",
        "EMBEDDING_MODEL",
        "OPENAI_API_KEY",
        "AI_WORKER_QUEUE",
        "CLOUDFLARE_AI_QUEUE_URL",
        "CLOUDFLARE_AI_QUEUE_SECRET",
        "CLOUDFLARE_AI_CALLBACK_SECRET",
        mode="before",
    )
    @classmethod
    def strip_env_strings(cls, value):
        if isinstance(value, str):
            return value.strip().strip('"').strip("'").strip()
        return value


def load_settings() -> Settings:
    if not IS_WORKERS:
        return Settings()
    from workers import env

    # Bindings are deployment configuration, not process environment variables.
    values = {}
    for name in Settings.model_fields:
        value = getattr(env, name, None)
        if isinstance(value, (str, int, float, bool)):
            values[name] = value
    values.setdefault("ENVIRONMENT", "production")
    values.setdefault("DOCUMENT_STORAGE_BACKEND", "supabase")
    values.setdefault("AI_WORKER_QUEUE", "cloudflare")
    return Settings(_env_file=None, **values)


settings = load_settings()

