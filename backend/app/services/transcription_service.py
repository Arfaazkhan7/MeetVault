import logging
import time
from typing import List, Dict, Optional, Any
from abc import ABC, abstractmethod
import whisper
import torch
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
            for segment in result["segments"]:
                segments.append({
                    "start_time": segment["start"],
                    "end_time": segment["end"],
                    "text": segment["text"].strip(),
                    "language": result.get("language"),
                    "confidence": segment.get("avg_logprob")
                })
            
            return {
                "segments": segments,
                "language": result.get("language"),
                "processing_time": processing_time
            }
            
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise


class TranscriptionService:
    """Service for managing audio transcription with async processing."""
    
    def __init__(self, engine: Optional[TranscriptionEngine] = None):
        """
        Initialize transcription service.
        
        Args:
            engine: Transcription engine to use (defaults to Whisper)
        """
        self.engine = engine or WhisperTranscriptionEngine()
        self.max_retries = 3
        self.retry_delay = 5  # seconds
    
    def transcribe_meeting(
        self,
        db: Session,
        meeting: Meeting,
        audio_path: str,
        language: Optional[str] = None
    ) -> List[TranscriptSegment]:
        """
        Transcribe meeting audio and save segments to database.
        
        Args:
            db: Database session
            meeting: Meeting instance
            audio_path: Path to audio file
            language: Optional language code
        
        Returns:
            List of created TranscriptSegment instances
        """
        # Update meeting status to processing
        meeting.transcription_status = "processing"
        meeting.transcription_error = None
        db.commit()
        
        try:
            # Transcribe with retry logic
            result = self._transcribe_with_retry(audio_path, language)
            
            # Clear existing transcripts for this meeting
            db.query(TranscriptSegment).filter(
                TranscriptSegment.meeting_id == meeting.id
            ).delete()
            
            # Create transcript segments
            segments = []
            for segment_data in result["segments"]:
                segment = TranscriptSegment(
                    meeting_id=meeting.id,
                    speaker_label="SPEAKER_0",  # Default until diarization is implemented
                    start_time=segment_data["start_time"],
                    end_time=segment_data["end_time"],
                    text=segment_data["text"],
                    language=segment_data["language"],
                    confidence=segment_data["confidence"]
                )
                db.add(segment)
                segments.append(segment)
            
            # Update meeting status
            meeting.transcription_status = "completed"
            db.commit()
            
            logger.info(f"Created {len(segments)} transcript segments for meeting {meeting.public_id}")
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
            TranscriptSegment.meeting_id == meeting.id
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
            TranscriptSegment.meeting_id == meeting.id
        ).count()
        
        return {
            "status": meeting.transcription_status,
            "error": meeting.transcription_error,
            "segment_count": segment_count,
            "recording_url": meeting.recording_url
        }