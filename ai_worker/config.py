import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip().strip('"').strip("'").strip()


@dataclass(frozen=True)
class WorkerSettings:
    broker_url: str = _env("REDIS_URL", "redis://localhost:6379/0")
    queue_backend: str = _env("AI_WORKER_QUEUE", "database")
    poll_interval_seconds: float = float(_env("AI_WORKER_POLL_INTERVAL_SECONDS", "5"))
    openai_api_key: str = _env("OPENAI_API_KEY")
    openai_model: str = _env("LLM_MODEL", "gpt-4o-mini")
    whisper_model: str = _env("WHISPER_MODEL", "small")
    transcription_provider: str = _env("TRANSCRIPTION_PROVIDER", "openai")
    analysis_provider: str = _env("LLM_PROVIDER", "openai")
    backend_callback_url: str = _env("AI_WORKER_CALLBACK_URL")
    hf_token: str = _env("HF_TOKEN")


settings = WorkerSettings()
