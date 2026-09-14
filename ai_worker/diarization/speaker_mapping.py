from typing import List
from ai_worker.schemas import TranscriptSegment
from .diarization import SpeakerTurn

def align_speakers(segments: List[TranscriptSegment], turns: List[SpeakerTurn]) -> List[TranscriptSegment]:
    """
    Align Whisper TranscriptSegments with Pyannote SpeakerTurns by finding the turn
    that has the maximum overlap with each segment.
    """
    if not turns:
        # Fallback if diarization failed or was skipped
        for seg in segments:
            seg.speaker_label = "SPEAKER_0"
        return segments

    for seg in segments:
        seg_start = seg.start_time
        seg_end = seg.end_time
        seg_duration = seg_end - seg_start

        best_speaker = "SPEAKER_0"
        max_overlap = 0.0

        for turn in turns:
            # Calculate overlap
            overlap_start = max(seg_start, turn.start)
            overlap_end = min(seg_end, turn.end)
            overlap = overlap_end - overlap_start

            if overlap > max_overlap:
                max_overlap = overlap
                best_speaker = turn.speaker

        seg.speaker_label = best_speaker

    return segments
