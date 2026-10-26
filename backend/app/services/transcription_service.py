import logging
import time
from typing import List, Dict, Optional, Any
from abc import ABC, abstractmethod
from sqlalchemy.orm import Session

from app.core.audio_temp import managed_temp_audio_file, safe_delete_temp_file
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
        cleanup_audio_after: bool = False,
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

            from app.models.meeting import MeetingParticipant
            participants = db.query(MeetingParticipant).filter(
                MeetingParticipant.meeting_id == meeting.public_id
            ).all()
            part_map = {p.user_id: p.id for p in participants if p.user_id}

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
                    uid = existing_seg.speaker_user_id or existing_seg.user_id
                    confirmed = True

                part_id = part_map.get(uid) if uid else (existing_seg.participant_id if existing_seg else None)
                attr_status = "confirmed" if confirmed else ("unconfirmed" if uid else "unknown")

                if existing_seg:
                    existing_seg.recording_id = recording_id or existing_seg.recording_id
                    existing_seg.segment_id = stable_id
                    existing_seg.start_time = segment_data["start_time"]
                    existing_seg.end_time = segment_data["end_time"]
                    existing_seg.text = segment_data["text"]
                    existing_seg.language = segment_data.get("language") or existing_seg.language
                    existing_seg.confidence = segment_data.get("confidence")
                    existing_seg.words = segment_data.get("words")
                    existing_seg.processing_metadata = {"engine": "whisper"}
                    if not existing_seg.speaker_confirmed:
                        existing_seg.speaker_label = spk
                        existing_seg.user_id = uid
                        existing_seg.speaker_user_id = uid
                        existing_seg.participant_id = part_id
                        existing_seg.speaker_confirmed = confirmed
                        existing_seg.attribution_status = attr_status
                    segments.append(existing_seg)
                else:
                    new_seg = TranscriptSegment(
                        meeting_id=meeting.public_id,
                        recording_id=recording_id,
                        segment_id=stable_id,
                        speaker_label=spk,
                        user_id=uid,
                        speaker_user_id=uid,
                        participant_id=part_id,
                        speaker_confirmed=confirmed,
                        attribution_status=attr_status,
                        start_time=segment_data["start_time"],
                        end_time=segment_data["end_time"],
                        text=segment_data["text"],
                        language=segment_data.get("language"),
                        confidence=segment_data.get("confidence"),
                        words=segment_data.get("words"),
                        processing_metadata={"engine": "whisper"},
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
        finally:
            if cleanup_audio_after and audio_path:
                deleted = safe_delete_temp_file(audio_path, reason="transcribe_meeting_cleanup")
                if not deleted:
                    try:
                        import os
                        if os.path.isfile(audio_path):
                            os.unlink(audio_path)
                            logger.info(f"[AUDIO_CLEANUP] Discarded temporary audio file {audio_path}")
                    except Exception as cleanup_err:
                        logger.warning(f"[AUDIO_CLEANUP_WARN] Failed to delete {audio_path}: {cleanup_err}")

    def transcribe_participant_audio_chunk(
        self,
        db: Session,
        meeting: Meeting,
        participant: Any,
        audio_bytes: bytes,
        language: Optional[str] = None,
        start_offset: float = 0.0,
        end_offset: Optional[float] = None,
        sequence_number: Optional[int] = None,
        chunk_id: Optional[str] = None,
        sample_rate: Optional[int] = None,
        frame_count: Optional[int] = None,
        chunk_duration: Optional[float] = None,
    ) -> List[TranscriptSegment]:
        """
        Process an identified participant's short-lived audio buffer.
        Audio bytes are buffered in memory and written to a short-lived ephemeral disk file
        in MeetVault's dedicated temporary directory because underlying transcription engines
        require a file path. The temporary file is actively tracked, unlinked immediately in a finally
        block upon transcription completion or failure, and covered by crash recovery cleanup.
        """
        import uuid

        if not audio_bytes or len(audio_bytes) == 0:
            return []

        # Create managed short-lived ephemeral temporary file in dedicated directory
        with managed_temp_audio_file(
            suffix=".wav",
            prefix="mv_audio_chunk_",
            meeting_id=meeting.public_id,
            content=audio_bytes,
        ) as tmp_audio_path:
            result = self._transcribe_with_retry(str(tmp_audio_path), language)

            # Assign to participant
            speaker_uid = participant.user_id
            part_id = participant.id
            attr_status = "verified_guest" if getattr(participant, "is_guest", False) else "verified"
            speaker_lbl = (
                f"SPEAKER_{participant.display_name or 'GUEST'}"
                if getattr(participant, "is_guest", False)
                else f"SPEAKER_{speaker_uid}"
            )

            metadata = {
                "engine": "whisper_participant_stream",
                "chunk_id": chunk_id,
                "sequence_number": sequence_number,
                "chunk_start_offset": start_offset,
                "chunk_end_offset": end_offset,
                "chunk_duration": chunk_duration,
                "sample_rate": sample_rate,
                "frame_count": frame_count,
                "timing_source": "audio_sample_clock",
            }

            segments = []
            result_segments = result.get("segments", [])
            batch_seg_ids = set()

            for idx, seg_data in enumerate(result_segments):
                raw_s = float(seg_data.get("start_time", 0.0))
                raw_e = float(seg_data.get("end_time", raw_s))

                # Guard against negative or inverted timings
                if raw_s < 0.0:
                    raw_s = 0.0
                if raw_e < raw_s:
                    raw_e = raw_s
                if chunk_duration and chunk_duration > 0 and raw_e > (chunk_duration + 0.2):
                    raw_e = chunk_duration

                s_time = round(raw_s + start_offset, 3)
                e_time = round(raw_e + start_offset, 3)

                base_seg_id = f"{meeting.public_id}_{part_id}_{int(s_time * 1000)}"
                seg_id = base_seg_id if idx == 0 and base_seg_id not in batch_seg_ids else f"{base_seg_id}_{idx}"
                batch_seg_ids.add(seg_id)

                existing_seg = db.query(TranscriptSegment).filter(
                    TranscriptSegment.meeting_id == meeting.public_id,
                    TranscriptSegment.segment_id == seg_id,
                ).first()

                if existing_seg:
                    existing_seg.text = seg_data["text"]
                    existing_seg.start_time = s_time
                    existing_seg.end_time = e_time
                    existing_seg.language = seg_data.get("language") or language or existing_seg.language
                    existing_seg.confidence = seg_data.get("confidence") or existing_seg.confidence
                    existing_seg.words = seg_data.get("words")
                    existing_seg.processing_metadata = metadata
                    segments.append(existing_seg)
                else:
                    seg = TranscriptSegment(
                        id=str(uuid.uuid4()),
                        meeting_id=meeting.public_id,
                        segment_id=seg_id,
                        speaker_label=speaker_lbl,
                        user_id=speaker_uid,
                        speaker_user_id=speaker_uid,
                        participant_id=part_id,
                        speaker_confirmed=True,
                        attribution_status=attr_status,
                        start_time=s_time,
                        end_time=e_time,
                        text=seg_data["text"],
                        language=seg_data.get("language") or language,
                        confidence=seg_data.get("confidence"),
                        words=seg_data.get("words"),
                        processing_metadata=metadata,
                    )
                    db.add(seg)
                    segments.append(seg)

            # Stage 4: Represent meeting as partial/in-progress while live transcription is active
            has_segments = len(segments) > 0 or db.query(TranscriptSegment).filter(
                TranscriptSegment.meeting_id == meeting.public_id
            ).count() > 0

            if meeting.transcription_status != "completed":
                if has_segments:
                    meeting.transcription_status = "partial"
                else:
                    meeting.transcription_status = "processing"
                meeting.transcription_error = None

            try:
                db.commit()
            except Exception as commit_exc:
                db.rollback()
                logger.error(
                    f"[CHUNK_PERSIST_ERROR] Database commit failed for meeting {meeting.public_id}, "
                    f"participant {part_id}: {commit_exc}"
                )
                raise RuntimeError(f"Database persistence failed: {commit_exc}") from commit_exc

            return segments
    
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

                # Fail fast on non-retryable / unrecoverable errors (e.g. file missing, invalid audio format)
                if isinstance(e, (FileNotFoundError, ValueError)):
                    logger.error(f"Permanent non-retryable transcription failure: {e}")
                    raise
                
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
        
        # All retries failed
        raise Exception(f"Transcription failed after {self.max_retries} attempts: {last_error}")
    
    def get_transcript_segments(
        self,
        db: Session,
        meeting_id: str,
        speaker_user_id: Optional[str] = None,
        participant_id: Optional[str] = None,
    ) -> List[TranscriptSegment]:
        """
        Retrieve transcript segments for an authorized meeting, with optional speaker filtering.
        
        Args:
            db: Database session
            meeting_id: Meeting public ID
            speaker_user_id: Optional user ID to filter by speaker
            participant_id: Optional participant ID to filter by participant
        
        Returns:
            List of TranscriptSegment instances ordered by start time
        """
        from app.services.meeting_service import get_meeting_by_public_id
        
        meeting = get_meeting_by_public_id(db, meeting_id)
        if not meeting:
            raise ValueError(f"Meeting not found: {meeting_id}")
        
        query = db.query(TranscriptSegment).filter(
            TranscriptSegment.meeting_id == meeting.public_id
        )
        if speaker_user_id:
            query = query.filter(
                (TranscriptSegment.speaker_user_id == speaker_user_id) | (TranscriptSegment.user_id == speaker_user_id)
            )
        if participant_id:
            query = query.filter(TranscriptSegment.participant_id == participant_id)

        segments = query.order_by(
            TranscriptSegment.start_time.asc(),
            TranscriptSegment.end_time.asc(),
        ).all()
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
        from app.core.enums import MeetingStatus, TranscriptionStatus
        
        meeting = get_meeting_by_public_id(db, meeting_id)
        if not meeting:
            raise ValueError(f"Meeting not found: {meeting_id}")
        
        # Stage 4: Safely finalize partial status if meeting has ended
        if (
            meeting.status == MeetingStatus.COMPLETED.value
            and meeting.transcription_status == TranscriptionStatus.PARTIAL.value
        ):
            meeting.transcription_status = TranscriptionStatus.COMPLETED.value
            try:
                db.commit()
            except Exception:
                db.rollback()

        segment_count = db.query(TranscriptSegment).filter(
            TranscriptSegment.meeting_id == meeting.public_id
        ).count()

        speaker_count = db.query(TranscriptSegment.speaker_label).filter(
            TranscriptSegment.meeting_id == meeting.public_id
        ).distinct().count()
        
        return {
            "status": meeting.transcription_status,
            "error": meeting.transcription_error,
            "segment_count": segment_count,
            "speaker_count": speaker_count,
            "recording_url": meeting.recording_url
        }
