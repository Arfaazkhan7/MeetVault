import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip().strip('"').strip("'").strip()


@dataclass(frozen=True)
class WorkerSettings:
    # Queue / broker
    broker_url: str = _env("REDIS_URL", "redis://localhost:6379/0")
    queue_backend: str = _env("AI_WORKER_QUEUE", "database")
    poll_interval_seconds: float = float(_env("AI_WORKER_POLL_INTERVAL_SECONDS", "5"))
    stale_job_minutes: int = int(_env("AI_WORKER_STALE_JOB_MINUTES", "30"))

    # OpenAI (kept for backward compat; only used if *_PROVIDER == "openai")
    openai_api_key: str = _env("OPENAI_API_KEY")
    openai_model: str = _env("LLM_MODEL", "gpt-4o-mini")
    whisper_model: str = _env("WHISPER_MODEL", "small")

    # Provider selection (defaults assume no OpenAI key is available)
    transcription_provider: str = _env("TRANSCRIPTION_PROVIDER", "huggingface")
    analysis_provider: str = _env("LLM_PROVIDER", "huggingface")

    # Hugging Face (used for whisper-large-v3 transcription)
    hf_token: str = _env("HF_TOKEN")
    hf_transcription_model: str = _env("HF_TRANSCRIPTION_MODEL", "openai/whisper-large-v3")
    hf_analysis_model: str = _env("HF_ANALYSIS_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")

    # pyannoteAI REST API (https://dashboard.pyannote.ai)
    # NOTE: pyannote/speaker-diarization-3.1 is NOT available on the generic
    #       HF Serverless Inference API.  Use pyannoteAI's managed REST endpoint.
    pyannoteai_api_key: str = _env("PYANNOTEAI_API_KEY")
    pyannoteai_api_url: str = _env("PYANNOTEAI_API_URL", "https://api.pyannote.ai/v1/diarize")

    # Worker internals
    backend_callback_url: str = _env("AI_WORKER_CALLBACK_URL")


settings = WorkerSettings()
