import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import settings
from .schemas import MeetingAnalysis, TranscriptSegment

logger = logging.getLogger(__name__)


def _require_openai():
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for the configured OpenAI AI worker")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install ai_worker requirements before using the OpenAI provider") from exc
    return OpenAI(api_key=settings.openai_api_key)


def transcribe(audio_path: str, language: Optional[str] = None) -> List[TranscriptSegment]:
    path = Path(audio_path)
    if not path.is_file():
        raise FileNotFoundError(f"Audio file does not exist: {audio_path}")

    if settings.transcription_provider.lower() == "local":
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


def analyze(title: str, segments: List[TranscriptSegment]) -> MeetingAnalysis:
    if settings.analysis_provider.lower() != "openai":
        raise RuntimeError("Only the OpenAI analysis provider is supported by the production worker")
    client = _require_openai()
    transcript = "\n".join(
        f"[{s.start_time:.1f}-{s.end_time:.1f}] {s.speaker_label or 'SPEAKER'}: {s.text}"
        for s in segments
    )
    response = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": (
                "Analyze meeting transcripts. Return JSON with summary, key_takeaways, topics, "
                "questions, answers, suggestions, proposals, concerns, agreements, disagreements, "
                "decisions, and action_items. Ground every extracted item in the transcript and "
                "include timestamp_range and speaker when applicable."
            )},
            {"role": "user", "content": f"Meeting: {title}\nTranscript:\n{transcript}"},
        ],
    )
    payload: Dict[str, Any] = json.loads(response.choices[0].message.content)
    fields = MeetingAnalysis.__dataclass_fields__
    return MeetingAnalysis(**{name: payload.get(name, "" if name == "summary" else []) for name in fields})
