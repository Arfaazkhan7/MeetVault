import logging
import time
from typing import List, Dict, Optional, Any
from abc import ABC, abstractmethod
from sqlalchemy.orm import Session

from app.models.meeting import Meeting
from app.models.transcript import TranscriptSegment

logger = logging.getLogger(__name__)


class TranscriptionEngine(ABC):
    """Abstract base class for transcription engines to allow easy replacement."""
    
    @abstractmethod
    def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        """Transcribe audio file and return structured results."""
        pass


class WhisperTranscriptionEngine(TranscriptionEngine):
    """Whisper-based transcription engine implementation."""
    
    def __init__(self, model_size: str = "base"):
        """
        Initialize Whisper model.
        
        Args:
            model_size: Whisper model size (tiny, base, small, medium, large)
        """
        self.model_size = model_size
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Load Whisper model."""
        try:
            import torch
            import whisper

            logger.info(f"Loading Whisper model: {self.model_size}")
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model = whisper.load_model(self.model_size, device=device)
            logger.info(f"Whisper model loaded on {device}")
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            raise
    
    def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        """
        Transcribe audio file using Whisper.
        
        Args:
            audio_path: Path to audio file
            language: Optional language code (e.g., 'en', 'es')
        
        Returns:
            Dictionary containing transcript segments with timestamps
        """
        try:
            import torch

            logger.info(f"Starting transcription for: {audio_path}")
            start_time = time.time()
            
            # Transcribe with timestamps
            result = self.model.transcribe(
                audio_path,
                language=language,
                word_timestamps=True,
                fp16=torch.cuda.is_available()
            )
            
            processing_time = time.time() - start_time
            logger.info(f"Transcription completed in {processing_time:.2f}s")
            
            # Extract segments with required information
            segments = []
            for segment in result.get("segments", []):
                text = segment.get("text", "").strip()
                if not text:
                    continue
                raw_logprob = segment.get("avg_logprob")
                # Genuine confidence from avg_logprob: exp(avg_logprob)
                conf = None
                if raw_logprob is not None:
                    try:
                        import math
                        val = float(raw_logprob)
                        if val <= 0.0:
                            conf = round(math.exp(val), 4) if val >= -10.0 else 0.0
                        elif 0.0 < val <= 1.0:
                            conf = round(val, 4)
                    except (ValueError, TypeError):
                        pass

                segments.append({
                    "start_time": segment["start"],
                    "end_time": segment["end"],
                    "text": text,
                    "language": result.get("language"),
                    "confidence": conf,
                    "words": segment.get("words"),
                })
            
            return {
                "segments": segments,
                "language": result.get("language"),
                "processing_time": processing_time
            }
            
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise


class LazyWhisperTranscriptionEngine(TranscriptionEngine):
    """Defers loading Whisper until transcription is actually requested."""

    def __init__(self, model_size: str = "base"):
        self.model_size = model_size
        self._engine: WhisperTranscriptionEngine | None = None

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        if self._engine is None:
            self._engine = WhisperTranscriptionEngine(self.model_size)
        return self._engine.transcribe(audio_path, language)


class TranscriptionService:
    """Service for managing audio transcription with async processing."""
    
    def __init__(self, engine: Optional[TranscriptionEngine] = None):
        """
        Initialize transcription service.
        
        Args:
            engine: Transcription engine to use (defaults to Whisper)
        """
        self.engine = engine or LazyWhisperTranscriptionEngine()
        self.max_retries = 3
        self.retry_delay = 5  # seconds
    
    def transcribe_meeting(
        self,
        db: Session,
        meeting: Meeting,
        audio_path: str,
        language: Optional[str] = None,
        recording_id: Optional[str] = None,
    ) -> List[TranscriptSegment]:
        """
        Transcribe meeting audio and save segments to database idempotently,
        preserving confirmed speaker mappings.
        
        Args:
            db: Database session
            meeting: Meeting instance
            audio_path: Path to audio file
            language: Optional language code
            recording_id: Optional recording ID
        
        Returns:
            List of created or updated TranscriptSegment instances
        """
        # Update meeting status to processing
        meeting.transcription_status = "processing"
        meeting.transcription_error = None
        db.commit()
        
        try:
            # Transcribe with retry logic
            result = self._transcribe_with_retry(audio_path, language)
            
            # Idempotently update or insert segments, preserving user-confirmed mappings
            existing_segments = db.query(TranscriptSegment).filter(
                TranscriptSegment.meeting_id == meeting.public_id
            ).all()
            existing_by_seg_id = {s.segment_id: s for s in existing_segments if s.segment_id}

            segments = []
            active_ids = set()
            for idx, segment_data in enumerate(result.get("segments", [])):
                stable_id = f"{meeting.public_id}:{idx:04d}"
                active_ids.add(stable_id)
                existing_seg = existing_by_seg_id.get(stable_id)
                if existing_seg is None and idx < len(existing_segments):
                    existing_seg = existing_segments[idx]

                spk = "SPEAKER_0"
                uid = None
                confirmed = False
                if existing_seg and existing_seg.speaker_confirmed:
                    spk = existing_seg.speaker_label
                    uid = existing_seg.user_id
                    confirmed = True

                if existing_seg:
                    existing_seg.recording_id = recording_id or existing_seg.recording_id
                    existing_seg.segment_id = stable_id
                    existing_seg.start_time = segment_data["start_time"]
                    existing_seg.end_time = segment_data["end_time"]
                    existing_seg.text = segment_data["text"]
                    existing_seg.language = segment_data.get("language") or existing_seg.language
                    existing_seg.confidence = segment_data.get("confidence")
                    existing_seg.words = segment_data.get("words")
                    if not existing_seg.speaker_confirmed:
                        existing_seg.speaker_label = spk
                        existing_seg.user_id = uid
                        existing_seg.speaker_confirmed = confirmed
                    segments.append(existing_seg)
                else:
                    new_seg = TranscriptSegment(
                        meeting_id=meeting.public_id,
                        recording_id=recording_id,
                        segment_id=stable_id,
                        speaker_label=spk,
                        user_id=uid,
                        speaker_confirmed=confirmed,
                        start_time=segment_data["start_time"],
                        end_time=segment_data["end_time"],
                        text=segment_data["text"],
                        language=segment_data.get("language"),
                        confidence=segment_data.get("confidence"),
                        words=segment_data.get("words"),
                    )
                    db.add(new_seg)
                    segments.append(new_seg)

            # Delete old stale unconfirmed segments that are no longer part of current transcription
            for old in existing_segments:
                if (old.segment_id not in active_ids) and not old.speaker_confirmed:
                    db.delete(old)

            # Update meeting status
            meeting.transcription_status = "completed"
            db.commit()
            
            logger.info(f"Persisted {len(segments)} transcript segments for meeting {meeting.public_id}")
            return segments
            
        except Exception as e:
            # Update meeting status with error
            meeting.transcription_status = "failed"
            meeting.transcription_error = str(e)
            db.commit()
            logger.error(f"Transcription failed for meeting {meeting.public_id}: {e}")
            raise
    
    def _transcribe_with_retry(
        self,
        audio_path: str,
        language: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Transcribe with retry logic for reliability.
        
        Args:
            audio_path: Path to audio file
            language: Optional language code
        
        Returns:
            Transcription result dictionary
        """
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                return self.engine.transcribe(audio_path, language)
            except Exception as e:
                last_error = e
                logger.warning(f"Transcription attempt {attempt + 1} failed: {e}")
                
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
        
        # All retries failed
        raise Exception(f"Transcription failed after {self.max_retries} attempts: {last_error}")
    
    def get_transcript_segments(
        self,
        db: Session,
        meeting_id: str
    ) -> List[TranscriptSegment]:
        """
        Retrieve transcript segments for a meeting.
        
        Args:
            db: Database session
            meeting_id: Meeting public ID
        
        Returns:
            List of TranscriptSegment instances ordered by start time
        """
        from app.services.meeting_service import get_meeting_by_public_id
        
        meeting = get_meeting_by_public_id(db, meeting_id)
        if not meeting:
            raise ValueError(f"Meeting not found: {meeting_id}")
        
        segments = db.query(TranscriptSegment).filter(
            TranscriptSegment.meeting_id == meeting.public_id
        ).order_by(TranscriptSegment.start_time).all()
        
        return segments
    
    def get_transcription_status(
        self,
        db: Session,
        meeting_id: str
    ) -> Dict[str, Any]:
        """
        Get transcription status for a meeting.
        
        Args:
            db: Database session
            meeting_id: Meeting public ID
        
        Returns:
            Dictionary with status information
        """
        from app.services.meeting_service import get_meeting_by_public_id
        
        meeting = get_meeting_by_public_id(db, meeting_id)
        if not meeting:
            raise ValueError(f"Meeting not found: {meeting_id}")
        
        segment_count = db.query(TranscriptSegment).filter(
            TranscriptSegment.meeting_id == meeting.public_id
        ).count()
        
        return {
            "status": meeting.transcription_status,
            "error": meeting.transcription_error,
            "segment_count": segment_count,
            "recording_url": meeting.recording_url
        }
