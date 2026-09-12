from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    PROJECT_NAME: str = "MeetVault"
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/meetingdb"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_SECRET: str = "change-this-to-a-very-long-random-secret-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # App
    ENVIRONMENT: str = "development"
    BACKEND_CORS_ORIGINS: str = ""
    API_BASE_URL: str = "http://localhost:8000/api/v1"

    @property
    def cors_origins(self) -> list[str]:
        if self.ENVIRONMENT == "development":
            return ["*"]
        return [
            origin.strip()
            for origin in self.BACKEND_CORS_ORIGINS.split(",")
            if origin.strip()
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


settings = Settings()
