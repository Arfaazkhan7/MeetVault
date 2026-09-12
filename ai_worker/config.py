import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerSettings:
    broker_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    whisper_model: str = os.getenv("WHISPER_MODEL", "small")
    transcription_provider: str = os.getenv("TRANSCRIPTION_PROVIDER", "openai")
    analysis_provider: str = os.getenv("LLM_PROVIDER", "openai")
    backend_callback_url: str = os.getenv("AI_WORKER_CALLBACK_URL", "")


settings = WorkerSettings()
