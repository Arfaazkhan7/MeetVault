"""
AI provider implementations for transcription and meeting analysis.

Supported transcription providers:
  - "huggingface" (default) — HF Inference API, no OpenAI key required
  - "openai"                — OpenAI Whisper API
  - "local"                 — openai-whisper loaded locally (large memory footprint)

Supported analysis providers:
  - "huggingface" (default) — HF Inference API LLM, no OpenAI key required
  - "openai"                — OpenAI Chat Completions
"""
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from .config import settings
from .schemas import MeetingAnalysis, TranscriptSegment

logger = logging.getLogger(__name__)

_HF_API_BASE = "https://api-inference.huggingface.co/models"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hf_headers() -> Dict[str, str]:
    if not settings.hf_token:
        raise RuntimeError(
            "HF_TOKEN environment variable is required for the Hugging Face provider"
        )
    return {"Authorization": f"Bearer {settings.hf_token}"}


def _hf_post_with_retry(url: str, **kwargs) -> requests.Response:
    """POST to a HF Inference endpoint, waiting up to 3× on 503 (model loading)."""
    backoff = 20
    for attempt in range(1, 4):
        resp = requests.post(url, timeout=300, **kwargs)
        if resp.status_code != 503:
            return resp
        wait = backoff * attempt
        logger.warning("HF model loading (503) — retrying in %ds (attempt %d/3)", wait, attempt)
        time.sleep(wait)
    return resp  # return last response even if still 503


def _require_openai():
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for the configured OpenAI AI worker")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install ai_worker requirements before using the OpenAI provider") from exc
    return OpenAI(api_key=settings.openai_api_key)


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

def transcribe(audio_path: str, language: Optional[str] = None) -> List[TranscriptSegment]:
    """Transcribe *audio_path* using the configured transcription provider."""
    path = Path(audio_path)
    if not path.is_file():
        raise FileNotFoundError(f"Audio file does not exist: {audio_path}")

    provider = settings.transcription_provider.lower()

    if provider == "huggingface":
        return _transcribe_huggingface(path, language)

    if provider == "local":
        return _transcribe_local(path, language)

    # Default / "openai"
    return _transcribe_openai(path, language)


def _transcribe_huggingface(path: Path, language: Optional[str]) -> List[TranscriptSegment]:
    """Transcribe via HF Inference API (openai/whisper-large-v3 or configured model)."""
    url = f"{_HF_API_BASE}/{settings.hf_transcription_model}"
    headers = {**_hf_headers(), "Content-Type": "audio/wav"}
    params: Dict[str, Any] = {"return_timestamps": True}
    if language:
        params["language"] = language

    logger.info("Transcribing via HF Inference API: %s", settings.hf_transcription_model)

    audio_bytes = path.read_bytes()
    resp = _hf_post_with_retry(url, headers=headers, data=audio_bytes, params=params)

    if resp.status_code == 503:
        raise RuntimeError(
            f"HF transcription model did not load after retries: {resp.text[:300]}"
        )
    if resp.status_code != 200:
        raise RuntimeError(
            f"HF transcription API error {resp.status_code}: {resp.text[:500]}"
        )

    return _parse_hf_transcription_response(resp.json())


def _parse_hf_transcription_response(data: Any) -> List[TranscriptSegment]:
    """
    Parse HF Whisper API response into TranscriptSegment list.

    HF returns one of:
      {"text": "...", "chunks": [{"timestamp": [0.0, 2.5], "text": "..."}, ...]}
    or (older format):
      {"text": "..."}  — no timestamp chunks
    """
    segments: List[TranscriptSegment] = []
    try:
        chunks = data.get("chunks") if isinstance(data, dict) else None

        if chunks:
            for chunk in chunks:
                ts = chunk.get("timestamp", [])
                text = chunk.get("text", "").strip()
                if not text:
                    continue
                start = float(ts[0]) if len(ts) > 0 and ts[0] is not None else 0.0
                end = float(ts[1]) if len(ts) > 1 and ts[1] is not None else start + 1.0
                segments.append(TranscriptSegment(start, end, text))
        else:
            # No chunks — create a single segment for the whole transcript
            full_text = (data.get("text", "") if isinstance(data, dict) else str(data)).strip()
            if full_text:
                segments.append(TranscriptSegment(0.0, 0.0, full_text))

        logger.info("HF transcription produced %d segment(s).", len(segments))
    except Exception as exc:
        logger.error("Failed to parse HF transcription response: %s", exc)
        raise

    return segments


def _transcribe_local(path: Path, language: Optional[str]) -> List[TranscriptSegment]:
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError("Install openai-whisper and torch for local transcription") from exc
    model = whisper.load_model(settings.whisper_model)
    result = model.transcribe(str(path), language=language, verbose=False)
    return [
        TranscriptSegment(float(item["start"]), float(item["end"]), item["text"].strip())
        for item in result.get("segments", [])
        if item.get("text", "").strip()
    ]


def _transcribe_openai(path: Path, language: Optional[str]) -> List[TranscriptSegment]:
    client = _require_openai()
    with path.open("rb") as audio:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio,
            language=language,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    return [
        TranscriptSegment(float(item.start), float(item.end), item.text.strip())
        for item in getattr(response, "segments", [])
        if getattr(item, "text", "").strip()
    ]


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

_ANALYSIS_SYSTEM_PROMPT = (
    "You are a meeting intelligence assistant. Analyze the following meeting transcript "
    "and return ONLY a valid JSON object with these exact keys: "
    "summary (string), key_takeaways (array), topics (array), questions (array), "
    "answers (array), suggestions (array), proposals (array), concerns (array), "
    "agreements (array), disagreements (array), decisions (array), action_items (array). "
    "Ground every item in the transcript. Include timestamp_range and speaker when possible."
)

_EMPTY_ANALYSIS = {
    "summary": "",
    "key_takeaways": [],
    "topics": [],
    "questions": [],
    "answers": [],
    "suggestions": [],
    "proposals": [],
    "concerns": [],
    "agreements": [],
    "disagreements": [],
    "decisions": [],
    "action_items": [],
}


def analyze(title: str, segments: List[TranscriptSegment]) -> MeetingAnalysis:
    """Analyze transcript segments using the configured analysis provider."""
    provider = settings.analysis_provider.lower()

    if provider == "huggingface":
        return _analyze_huggingface(title, segments)

    # Default / "openai"
    return _analyze_openai(title, segments)


def _build_transcript_text(title: str, segments: List[TranscriptSegment]) -> str:
    lines = [f"Meeting: {title}", "Transcript:"]
    for s in segments:
        speaker = s.speaker_label or "SPEAKER"
        lines.append(f"[{s.start_time:.1f}-{s.end_time:.1f}] {speaker}: {s.text}")
    return "\n".join(lines)


def _analyze_huggingface(title: str, segments: List[TranscriptSegment]) -> MeetingAnalysis:
    """Analyze via HF Inference API text-generation endpoint."""
    transcript = _build_transcript_text(title, segments)

    prompt = (
        f"<s>[INST] {_ANALYSIS_SYSTEM_PROMPT}\n\n{transcript} [/INST]"
    )

    url = f"{_HF_API_BASE}/{settings.hf_analysis_model}"
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 1024,
            "temperature": 0.2,
            "return_full_text": False,
        },
    }

    logger.info("Analyzing meeting via HF Inference API: %s", settings.hf_analysis_model)

    resp = _hf_post_with_retry(url, headers=_hf_headers(), json=payload)

    if resp.status_code == 503:
        logger.warning("HF analysis model did not load after retries; returning empty analysis.")
        return _empty_analysis()

    if resp.status_code != 200:
        logger.error("HF analysis API error %d: %s", resp.status_code, resp.text[:500])
        return _empty_analysis()

    return _parse_hf_analysis_response(resp.json(), title)


def _parse_hf_analysis_response(data: Any, title: str) -> MeetingAnalysis:
    """Parse text-generation response and extract the JSON block."""
    try:
        if isinstance(data, list) and data:
            generated = data[0].get("generated_text", "")
        elif isinstance(data, dict):
            generated = data.get("generated_text", "")
        else:
            generated = str(data)

        # Find the first {...} JSON block in the generated text
        start = generated.find("{")
        end = generated.rfind("}") + 1
        if start == -1 or end == 0:
            logger.warning("No JSON object found in HF analysis response; using empty analysis.")
            return _empty_analysis()

        payload: Dict[str, Any] = json.loads(generated[start:end])
        fields = MeetingAnalysis.__dataclass_fields__
        return MeetingAnalysis(**{
            name: payload.get(name, "" if name == "summary" else [])
            for name in fields
        })
    except Exception as exc:
        logger.error("Failed to parse HF analysis response: %s", exc)
        return _empty_analysis()


def _empty_analysis() -> MeetingAnalysis:
    return MeetingAnalysis(**_EMPTY_ANALYSIS)


def _analyze_openai(title: str, segments: List[TranscriptSegment]) -> MeetingAnalysis:
    client = _require_openai()
    transcript = _build_transcript_text(title, segments)
    response = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
    )
    payload: Dict[str, Any] = json.loads(response.choices[0].message.content)
    fields = MeetingAnalysis.__dataclass_fields__
    return MeetingAnalysis(**{name: payload.get(name, "" if name == "summary" else []) for name in fields})
