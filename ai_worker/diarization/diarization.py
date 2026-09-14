import logging
from typing import List, Dict, Any
from ai_worker.config import settings

logger = logging.getLogger(__name__)

class SpeakerTurn:
    def __init__(self, start: float, end: float, speaker: str):
        self.start = start
        self.end = end
        self.speaker = speaker

    def __repr__(self):
        return f"<SpeakerTurn {self.speaker} [{self.start:.2f}-{self.end:.2f}]>"

def diarize(audio_path: str) -> List[SpeakerTurn]:
    """
    Run Pyannote audio speaker diarization on the provided audio file.
    Requires HF_TOKEN to be set in environment for pyannote/speaker-diarization-3.1
    """
    if not settings.hf_token:
        logger.warning("HF_TOKEN is not set. Speaker diarization cannot run. Falling back to single speaker.")
        # Without a token, we return an empty list, and the mapping will fallback to SPEAKER_0
        return []

    try:
        import torch
        from pyannote.audio import Pipeline
    except ImportError as e:
        logger.error("pyannote.audio or torch is not installed.")
        raise e

    logger.info("Loading Pyannote diarization pipeline...")
    # Load pipeline
    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=settings.hf_token
        )
    except Exception as e:
        logger.error(f"Failed to load pyannote pipeline. Ensure HF_TOKEN is valid and terms are accepted: {e}")
        return []

    # Send pipeline to GPU if available
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    pipeline.to(device)

    logger.info(f"Running diarization on {audio_path} using {device}...")
    diarization = pipeline(audio_path)

    turns = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        turns.append(SpeakerTurn(start=turn.start, end=turn.end, speaker=speaker))

    logger.info(f"Diarization complete. Found {len(turns)} speaker turns.")
    return turns
