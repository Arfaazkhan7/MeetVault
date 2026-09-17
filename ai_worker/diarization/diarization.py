"""
Speaker diarization via Hugging Face Inference API.

Calls pyannote/speaker-diarization-3.1 remotely — no local model loading,
no torch, no pyannote.audio dependency.

If the endpoint is unavailable (free-tier restriction, 402/403) or HF_TOKEN
is not set, the function returns an empty list. The caller (speaker_mapping.py)
handles this gracefully by assigning all segments to SPEAKER_0.
"""
import logging
import time
from pathlib import Path
from typing import List

import requests

from ai_worker.config import settings

logger = logging.getLogger(__name__)

_HF_API_BASE = "https://api-inference.huggingface.co/models"


class SpeakerTurn:
    def __init__(self, start: float, end: float, speaker: str):
        self.start = start
        self.end = end
        self.speaker = speaker

    def __repr__(self):
        return f"<SpeakerTurn {self.speaker} [{self.start:.2f}-{self.end:.2f}]>"


def diarize(audio_path: str) -> List[SpeakerTurn]:
    """
    Run speaker diarization on *audio_path* using the HF Inference API.

    Returns a list of SpeakerTurn objects on success, or an empty list when:
      - HF_TOKEN is not configured
      - The model endpoint is not accessible (402/403 = paid tier only)
      - The audio file cannot be read
    """
    if not settings.hf_token:
        logger.warning(
            "HF_TOKEN is not set. Speaker diarization skipped; "
            "all segments will be labelled SPEAKER_0."
        )
        return []

    audio_file = Path(audio_path)
    if not audio_file.is_file():
        logger.error("Audio file not found: %s", audio_path)
        return []

    url = f"{_HF_API_BASE}/{settings.hf_diarization_model}"
    headers = {
        "Authorization": f"Bearer {settings.hf_token}",
        "Content-Type": "audio/wav",
    }

    audio_bytes = audio_file.read_bytes()

    max_retries = 3
    backoff = 20  # seconds — HF returns 503 while loading the model

    for attempt in range(1, max_retries + 1):
        logger.info(
            "Diarization request to HF API (attempt %d/%d): %s",
            attempt, max_retries, settings.hf_diarization_model,
        )
        try:
            resp = requests.post(
                url,
                headers=headers,
                data=audio_bytes,
                timeout=300,  # diarization can take a while on large files
            )
        except requests.exceptions.RequestException as exc:
            logger.error("Diarization HTTP request failed: %s", exc)
            return []

        if resp.status_code == 200:
            return _parse_diarization_response(resp.json())

        if resp.status_code == 503:
            # Model is loading on HF side — wait and retry
            wait = backoff * attempt
            logger.warning(
                "HF diarization model loading (503). Retrying in %ds…", wait
            )
            time.sleep(wait)
            continue

        if resp.status_code in (402, 403):
            logger.warning(
                "HF diarization endpoint requires a paid plan (HTTP %d). "
                "Falling back to single-speaker mode (SPEAKER_0).",
                resp.status_code,
            )
            return []

        # Any other error — log and give up
        logger.error(
            "HF diarization returned unexpected status %d: %s",
            resp.status_code, resp.text[:500],
        )
        return []

    logger.warning(
        "HF diarization model did not load after %d attempts. "
        "Falling back to single-speaker mode.",
        max_retries,
    )
    return []


def _parse_diarization_response(data) -> List[SpeakerTurn]:
    """
    Parse the HF Inference API diarization response.

    The API returns a list of dicts:
      [{"label": "SPEAKER_00", "score": 0.98, "start": 0.0, "end": 3.5}, ...]
    or nested under "output" depending on the model version.
    """
    turns = []
    try:
        if isinstance(data, dict):
            # Some versions wrap the list under "output"
            items = data.get("output", data.get("segments", []))
        elif isinstance(data, list):
            items = data
        else:
            logger.error("Unexpected diarization response type: %s", type(data))
            return []

        for item in items:
            speaker = item.get("label") or item.get("speaker") or "SPEAKER_0"
            start = float(item.get("start", 0.0))
            end = float(item.get("end", 0.0))
            if end > start:
                turns.append(SpeakerTurn(start=start, end=end, speaker=speaker))

        logger.info("Diarization complete — %d speaker turn(s) parsed.", len(turns))
    except Exception as exc:
        logger.error("Failed to parse diarization response: %s", exc)
        return []

    return turns
