import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip().strip('"').strip("'").strip()


@dataclass(frozen=True)
class WorkerSettings:
    broker_url: str = _env("REDIS_URL", "redis://localhost:6379/0")
    queue_backend: str = _env("AI_WORKER_QUEUE", "database")
    poll_interval_seconds: float = float(_env("AI_WORKER_POLL_INTERVAL_SECONDS", "5"))
    stale_job_minutes: int = int(_env("AI_WORKER_STALE_JOB_MINUTES", "30"))

    # OpenAI (kept for backward compatibility; only used if *_PROVIDER == "openai")
    openai_api_key: str = _env("OPENAI_API_KEY")
    openai_model: str = _env("LLM_MODEL", "gpt-4o-mini")
    whisper_model: str = _env("WHISPER_MODEL", "small")

    # Provider selection — default to "huggingface" so no OpenAI key is required
    transcription_provider: str = _env("TRANSCRIPTION_PROVIDER", "huggingface")
    analysis_provider: str = _env("LLM_PROVIDER", "huggingface")

    # Hugging Face
    hf_token: str = _env("HF_TOKEN")
    hf_transcription_model: str = _env("HF_TRANSCRIPTION_MODEL", "openai/whisper-large-v3")
    hf_analysis_model: str = _env("HF_ANALYSIS_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")
    hf_diarization_model: str = _env("HF_DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1")

    # Worker internals
    backend_callback_url: str = _env("AI_WORKER_CALLBACK_URL")


settings = WorkerSettings()
