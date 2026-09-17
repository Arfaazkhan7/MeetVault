"""
Speaker diarization via pyannoteAI REST API (https://api.pyannote.ai).

IMPORTANT: pyannote/speaker-diarization-3.1 is NOT available on the generic
Hugging Face Serverless Inference API. Any code calling:
  https://api-inference.huggingface.co/models/pyannote/speaker-diarization-3.1
will receive a 404/403 error — that endpoint does not exist for this model.

The correct approach is to use the pyannoteAI managed REST API:
  POST https://api.pyannote.ai/v1/diarize
with an audio URL and a PYANNOTEAI_API_KEY from https://dashboard.pyannote.ai

The audio URL is a time-limited Supabase signed URL created by the pipeline
before calling this module.

Required environment variable: PYANNOTEAI_API_KEY
"""
import logging
import time
from typing import List, Optional

import requests

from ai_worker.config import settings

logger = logging.getLogger(__name__)


class SpeakerTurn:
    """Represents a single speaker turn from diarization."""

    def __init__(self, start: float, end: float, speaker: str):
        self.start = start
        self.end = end
        self.speaker = speaker

    def __repr__(self):
        return f"<SpeakerTurn {self.speaker} [{self.start:.3f}-{self.end:.3f}]>"


class DiarizationError(Exception):
    """Raised when diarization fails for a known, reportable reason."""
    pass


def diarize(audio_url: str) -> List[SpeakerTurn]:
    """
    Run speaker diarization on the audio at *audio_url* using pyannoteAI.

    Args:
        audio_url: A publicly accessible URL to the audio file.
                   For Supabase recordings, pass a time-limited signed URL.

    Returns:
        List of SpeakerTurn objects (speaker, start, end).

    Raises:
        DiarizationError: If the API key is missing, authentication fails,
                          the rate limit is hit, or the audio is invalid.
        RuntimeError:     If an unexpected API failure occurs.
    """
    _validate_config()

    logger.info("Submitting diarization job to pyannoteAI: %s", settings.pyannoteai_api_url)

    headers = {
        "Authorization": f"Bearer {settings.pyannoteai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {"url": audio_url}

    try:
        resp = requests.post(
            settings.pyannoteai_api_url,
            headers=headers,
            json=payload,
            timeout=300,
        )
    except requests.exceptions.Timeout:
        raise DiarizationError(
            "pyannoteAI diarization request timed out after 300 seconds."
        )
    except requests.exceptions.RequestException as exc:
        raise DiarizationError(f"pyannoteAI network error: {exc}") from exc

    _check_response_errors(resp)

    data = resp.json()
    return _parse_response(data)


def _validate_config():
    """Raise DiarizationError if the API key is not configured."""
    if not settings.pyannoteai_api_key:
        raise DiarizationError(
            "PYANNOTEAI_API_KEY is not configured. "
            "Register at https://dashboard.pyannote.ai and set this environment variable. "
            "NOTE: HF_TOKEN alone does not provide access to pyannoteAI."
        )


def _check_response_errors(resp: requests.Response):
    """Map HTTP status codes to descriptive DiarizationError messages."""
    if resp.status_code == 200:
        return  # success

    # Try to extract error detail from JSON body
    try:
        body = resp.json()
        detail = body.get("detail") or body.get("message") or body.get("error") or str(body)
    except Exception:
        detail = resp.text[:300] if resp.text else "(empty response)"

    if resp.status_code == 401:
        raise DiarizationError(
            f"pyannoteAI authentication failed (401). "
            f"Check that PYANNOTEAI_API_KEY is valid. Detail: {detail}"
        )
    if resp.status_code == 402:
        raise DiarizationError(
            f"pyannoteAI payment required (402). Your free credits may be exhausted. "
            f"Check https://dashboard.pyannote.ai. Detail: {detail}"
        )
    if resp.status_code == 429:
        raise DiarizationError(
            f"pyannoteAI rate limit exceeded (429). Try again later. Detail: {detail}"
        )
    if resp.status_code == 422:
        raise DiarizationError(
            f"pyannoteAI rejected the audio URL (422 Unprocessable Entity). "
            f"The signed URL may have expired or be unreachable. Detail: {detail}"
        )
    if resp.status_code >= 500:
        raise DiarizationError(
            f"pyannoteAI server error ({resp.status_code}). Detail: {detail}"
        )

    raise DiarizationError(
        f"pyannoteAI returned unexpected status {resp.status_code}. Detail: {detail}"
    )


def _parse_response(data: dict) -> List[SpeakerTurn]:
    """
    Parse pyannoteAI diarization response.

    The API returns:
    {
      "output": {
        "diarization": [
          {"speaker": "SPEAKER_00", "start": 0.0, "end": 4.25},
          {"speaker": "SPEAKER_01", "start": 4.25, "end": 8.90},
          ...
        ]
      }
    }

    Some versions may return diarization at the top level.
    """
    turns: List[SpeakerTurn] = []

    try:
        # Try nested under "output.diarization" first
        output = data.get("output", {})
        if isinstance(output, dict):
            segments = output.get("diarization", [])
        else:
            segments = []

        # Fallback: top-level "diarization" key
        if not segments:
            segments = data.get("diarization", [])

        # Fallback: top-level list
        if not segments and isinstance(data, list):
            segments = data

        for item in segments:
            speaker = item.get("speaker") or item.get("label") or "SPEAKER_UNKNOWN"
            start = float(item.get("start", 0.0))
            end = float(item.get("end", 0.0))
            if end > start:
                turns.append(SpeakerTurn(start=start, end=end, speaker=speaker))

        if not turns:
            logger.warning(
                "pyannoteAI returned 0 speaker turns. "
                "Raw response: %s", str(data)[:500]
            )
        else:
            unique_speakers = len(set(t.speaker for t in turns))
            logger.info(
                "Diarization complete: %d turn(s), %d unique speaker(s).",
                len(turns), unique_speakers
            )

    except Exception as exc:
        raise DiarizationError(
            f"Failed to parse pyannoteAI response: {exc}. Raw: {str(data)[:500]}"
        ) from exc

    return turns
