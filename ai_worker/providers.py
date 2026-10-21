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
import math
import tempfile
import time
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.core.audio_temp import create_temp_audio_file, safe_delete_temp_file
from .config import settings
from .schemas import MeetingAnalysis, TranscriptSegment

logger = logging.getLogger(__name__)

_HF_API_BASE = "https://api-inference.huggingface.co/models"

# ---------------------------------------------------------------------------
# Multilingual Support Matrix & Language Evaluation
# ---------------------------------------------------------------------------

LANGUAGE_SUPPORT_MATRIX: Dict[str, Dict[str, Any]] = {
    "en": {
        "name": "English",
        "iso_639_1": "en",
        "supported": True,
        "tier": "Tier 1 Native",
        "code_switching_capable": True,
        "script": "Latin",
        "notes": "Optimal accuracy, extensive training data.",
    },
    "ta": {
        "name": "Tamil",
        "iso_639_1": "ta",
        "supported": True,
        "tier": "Tier 1 Native",
        "code_switching_capable": True,
        "script": "Tamil",
        "notes": "Native Whisper Large v3 support. Handles Tamil script and Tanglish code-switching.",
    },
    "hi": {
        "name": "Hindi",
        "iso_639_1": "hi",
        "supported": True,
        "tier": "Tier 1 Native",
        "code_switching_capable": True,
        "script": "Devanagari",
        "notes": "Native Whisper Large v3 support. Handles Devanagari script and Hinglish code-switching.",
    },
    "auto": {
        "name": "Automatic Detection",
        "iso_639_1": None,
        "supported": True,
        "tier": "Auto Detection",
        "code_switching_capable": True,
        "script": "Multilingual",
        "notes": "Whisper detects spoken language automatically per audio stream.",
    },
}


def evaluate_language_support(language_code: Optional[str]) -> Dict[str, Any]:
    """
    Validate and evaluate model support for a given language code.
    Do not claim support for languages that the configured ASR cannot reliably handle.
    """
    if not language_code or language_code.lower().strip() in ("auto", "none", ""):
        return {
            "requested_language": language_code,
            "normalized_code": "auto",
            "supported": True,
            "tier": "Auto Detection",
            "code_switching_capable": True,
            "script": "Multilingual",
            "provider_model": settings.hf_transcription_model,
            "notes": "Automatic language identification enabled.",
        }

    code = language_code.lower().strip()
    if code in LANGUAGE_SUPPORT_MATRIX:
        info = LANGUAGE_SUPPORT_MATRIX[code]
        return {
            "requested_language": language_code,
            "normalized_code": code,
            "supported": True,
            "tier": info["tier"],
            "code_switching_capable": info["code_switching_capable"],
            "script": info["script"],
            "provider_model": settings.hf_transcription_model,
            "notes": info["notes"],
        }

    return {
        "requested_language": language_code,
        "normalized_code": code,
        "supported": False,
        "tier": "Unsupported / Unverified",
        "code_switching_capable": False,
        "script": "Unknown",
        "provider_model": settings.hf_transcription_model,
        "notes": f"Language code '{language_code}' is not verified for reliable ASR in current configuration.",
    }


def _extract_confidence(raw_val: Any) -> Optional[float]:
    """
    Extract genuine confidence score bounded to [0.0, 1.0].
    Whisper emits avg_logprob (<= 0.0). We compute exp(avg_logprob).
    If raw_val is already [0.0, 1.0] probability, preserve it.
    If no confidence/logprob is present, return None (never invent fake confidence).
    """
    if raw_val is None:
        return None
    try:
        val = float(raw_val)
        if math.isnan(val) or math.isinf(val):
            return None
        if val <= 0.0:
            if val < -10.0:
                return 0.0
            return round(math.exp(val), 4)
        if 0.0 < val <= 1.0:
            return round(val, 4)
        return None
    except (ValueError, TypeError):
        return None


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
    """POST to a HF Inference endpoint with exponential backoff on 503 (loading) and 429 (rate-limit)."""
    backoff = 10
    resp = None
    for attempt in range(1, 4):
        resp = requests.post(url, timeout=300, **kwargs)
        if resp.status_code not in (503, 429):
            return resp
        wait = backoff * attempt
        logger.warning(
            "HF Inference status %d (attempt %d/3) — retrying in %ds...",
            resp.status_code,
            attempt,
            wait,
        )
        time.sleep(wait)
    return resp if resp is not None else requests.post(url, timeout=300, **kwargs)


def _require_openai():
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for the configured OpenAI AI worker")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install ai_worker requirements before using the OpenAI provider") from exc
    return OpenAI(api_key=settings.openai_api_key)


# ---------------------------------------------------------------------------
# Chunking for Long Audio
# ---------------------------------------------------------------------------

def _get_wav_duration_seconds(path: Path) -> Optional[float]:
    """Return WAV duration in seconds using standard library wave, or None if not WAV."""
    try:
        with wave.open(str(path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate <= 0:
                return None
            return float(frames) / float(rate)
    except Exception:
        return None


def _chunk_wav_file(
    path: Path,
    chunk_duration_sec: float = 300.0,
    overlap_sec: float = 2.0,
) -> List[Tuple[Path, float]]:
    """
    Split a WAV file into smaller temporal chunks with overlap.
    Returns list of (temp_chunk_path, start_offset_seconds).
    Caller is responsible for cleaning up temporary files.
    """
    chunks: List[Tuple[Path, float]] = []
    try:
        with wave.open(str(path), "rb") as wf:
            params = wf.getparams()
            framerate = params.framerate
            nframes = params.nframes
            sampwidth = params.sampwidth
            nchannels = params.nchannels

            if framerate <= 0 or nframes <= 0:
                return [(path, 0.0)]

            total_duration = float(nframes) / float(framerate)
            if total_duration <= chunk_duration_sec:
                return [(path, 0.0)]

            chunk_frames = int(chunk_duration_sec * framerate)
            step_frames = int((chunk_duration_sec - overlap_sec) * framerate)
            if step_frames <= 0:
                step_frames = chunk_frames

            curr_frame = 0
            while curr_frame < nframes:
                wf.setpos(curr_frame)
                frames_to_read = min(chunk_frames, nframes - curr_frame)
                audio_data = wf.readframes(frames_to_read)

                chunk_file = create_temp_audio_file(
                    suffix=".wav",
                    prefix="mv_audio_chunk_",
                )
                with wave.open(str(chunk_file), "wb") as cwf:
                    cwf.setnchannels(nchannels)
                    cwf.setsampwidth(sampwidth)
                    cwf.setframerate(framerate)
                    cwf.writeframes(audio_data)

                offset_sec = float(curr_frame) / float(framerate)
                chunks.append((chunk_file, offset_sec))

                curr_frame += step_frames
                if curr_frame >= nframes:
                    break

        return chunks
    except Exception as exc:
        logger.warning("Could not chunk WAV file (%s). Falling back to single pass: %s", path, exc)
        return [(path, 0.0)]


def _merge_chunk_segments(
    chunk_results: List[Tuple[List[TranscriptSegment], float]]
) -> List[TranscriptSegment]:
    """
    Merge segments across temporal chunks, adjusting timestamps by chunk offsets
    and deduplicating overlapping boundary segments.
    """
    merged: List[TranscriptSegment] = []
    for segments, offset in chunk_results:
        for seg in segments:
            shifted_start = round(seg.start_time + offset, 3)
            shifted_end = round(seg.end_time + offset, 3)

            # Check boundary overlap with previously accepted segment
            if merged:
                last_seg = merged[-1]
                # If exact duplicate text within overlap window, skip
                if (
                    last_seg.text.strip().lower() == seg.text.strip().lower()
                    and abs(shifted_start - last_seg.start_time) < 3.0
                ):
                    continue
                # If end time is before last start, avoid retrograding
                if shifted_end <= last_seg.start_time:
                    continue

            # Update segment timestamps with absolute global timing
            seg.start_time = shifted_start
            seg.end_time = max(shifted_end, shifted_start + 0.1)
            merged.append(seg)

    return merged


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

def transcribe(
    audio_path: str,
    language: Optional[str] = None,
    allow_chunking: bool = True,
) -> List[TranscriptSegment]:
    """
    Transcribe *audio_path* using the configured transcription provider.
    Handles long audio chunking with timestamp offsets, language support evaluation,
    silence, and metadata preservation.
    """
    path = Path(audio_path)
    if not path.is_file():
        raise FileNotFoundError(f"Audio file does not exist: {audio_path}")

    # Check for empty audio file
    if path.stat().st_size == 0:
        logger.info("Audio file is 0 bytes; returning empty transcript.")
        return []

    # Evaluate requested language support
    lang_info = evaluate_language_support(language)
    logger.info("ASR language evaluation: %s", lang_info)

    # Check audio duration and chunk if needed
    duration = _get_wav_duration_seconds(path)
    if allow_chunking and duration and duration > 300.0:
        logger.info("Long audio detected (%.1fs > 300s). Chunking audio with overlap...", duration)
        chunks = _chunk_wav_file(path, chunk_duration_sec=300.0, overlap_sec=2.0)
        chunk_results: List[Tuple[List[TranscriptSegment], float]] = []
        try:
            for chunk_path, offset in chunks:
                segs = _transcribe_single_audio(chunk_path, language)
                chunk_results.append((segs, offset))
            return _merge_chunk_segments(chunk_results)
        finally:
            for chunk_path, _ in chunks:
                if chunk_path != path:
                    safe_delete_temp_file(chunk_path, reason="chunk_transcription_complete")

    return _transcribe_single_audio(path, language)


def _transcribe_single_audio(path: Path, language: Optional[str]) -> List[TranscriptSegment]:
    """Transcribe single audio chunk using configured provider."""
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

    return _parse_hf_transcription_response(resp.json(), fallback_language=language)


def _parse_hf_transcription_response(
    data: Any,
    fallback_language: Optional[str] = None,
) -> List[TranscriptSegment]:
    """
    Parse HF Whisper API response into TranscriptSegment list.
    Preserves detected language, genuine confidence from avg_logprob,
    word-level timestamps, and translated text if present.
    """
    segments: List[TranscriptSegment] = []
    try:
        if isinstance(data, list) and len(data) > 0:
            data = data[0]

        top_level_lang = data.get("language") if isinstance(data, dict) else None
        chunks = data.get("chunks") if isinstance(data, dict) else None

        if chunks:
            for chunk in chunks:
                ts = chunk.get("timestamp", [])
                text = chunk.get("text", "").strip()
                if not text:
                    continue
                start = float(ts[0]) if len(ts) > 0 and ts[0] is not None else 0.0
                end = float(ts[1]) if len(ts) > 1 and ts[1] is not None else start + 1.0
                chunk_lang = chunk.get("language") or top_level_lang or fallback_language
                raw_conf = chunk.get("avg_logprob", chunk.get("confidence", chunk.get("score")))
                confidence = _extract_confidence(raw_conf)
                translated_text = chunk.get("translated_text", chunk.get("translation"))
                words = chunk.get("words")

                segments.append(
                    TranscriptSegment(
                        start_time=start,
                        end_time=end,
                        text=text,
                        language=chunk_lang,
                        confidence=confidence,
                        translated_text=translated_text,
                        words=words,
                    )
                )
        else:
            # Single transcript without chunks
            full_text = (data.get("text", "") if isinstance(data, dict) else str(data)).strip()
            if full_text:
                raw_conf = data.get("avg_logprob", data.get("confidence")) if isinstance(data, dict) else None
                confidence = _extract_confidence(raw_conf)
                detected_lang = top_level_lang or fallback_language
                translated_text = data.get("translated_text", data.get("translation")) if isinstance(data, dict) else None
                segments.append(
                    TranscriptSegment(
                        start_time=0.0,
                        end_time=0.0,
                        text=full_text,
                        language=detected_lang,
                        confidence=confidence,
                        translated_text=translated_text,
                    )
                )

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
    detected_lang = result.get("language")
    segments = []
    for item in result.get("segments", []):
        text = item.get("text", "").strip()
        if not text:
            continue
        start = float(item.get("start", 0.0))
        end = float(item.get("end", start + 1.0))
        raw_logprob = item.get("avg_logprob")
        conf = _extract_confidence(raw_logprob)
        words = item.get("words")
        segments.append(
            TranscriptSegment(
                start_time=start,
                end_time=end,
                text=text,
                language=detected_lang,
                confidence=conf,
                words=words,
            )
        )
    return segments


def _transcribe_openai(path: Path, language: Optional[str]) -> List[TranscriptSegment]:
    client = _require_openai()
    with path.open("rb") as audio:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio,
            language=language,
            response_format="verbose_json",
            timestamp_granularities=["segment", "word"],
        )
    detected_lang = getattr(response, "language", None)
    segments = []
    for item in getattr(response, "segments", []):
        text = getattr(item, "text", "").strip()
        if not text:
            continue
        start = float(getattr(item, "start", 0.0))
        end = float(getattr(item, "end", start + 1.0))
        raw_logprob = getattr(item, "avg_logprob", None)
        conf = _extract_confidence(raw_logprob)
        words = getattr(item, "words", None)
        segments.append(
            TranscriptSegment(
                start_time=start,
                end_time=end,
                text=text,
                language=detected_lang,
                confidence=conf,
                words=words,
            )
        )
    return segments


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
