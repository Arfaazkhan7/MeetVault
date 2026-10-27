from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
import os
import tempfile
import math
import wave
import io

from app.core.config import settings
from app.core.audio_temp import create_temp_audio_file, safe_delete_temp_file
from app.db.session import get_db
from app.core.dependencies import get_current_user
from app.core.meeting_dependencies import get_meeting_and_authorize, require_meeting_host
from app.models.user import User
from app.models.meeting import Meeting, MeetingParticipant
from app.models.transcript import TranscriptSegment
from app.schemas.transcript import TranscriptSegmentResponse
from app.services.transcription_service import TranscriptionService
from app.services.speaker_mapping_service import SpeakerMappingService
from app.workers import submit_transcription_job

router = APIRouter(prefix="/transcripts", tags=["transcripts"])

# 25 MB max per audio chunk in live streaming (sufficient for up to 5 mins of 48kHz stereo)
MAX_AUDIO_CHUNK_BYTES: int = 25 * 1024 * 1024


@router.get("/meetings/{meeting_id}")
def get_transcript(
    meeting_id: str,
    speaker_user_id: Optional[str] = None,
    participant_id: Optional[str] = None,
    meeting: Meeting = Depends(get_meeting_and_authorize),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get transcript segments for an authorized meeting.
    Supports optional filtering by speaker_user_id or participant_id.
    Validates speaker membership to ensure tenant and meeting isolation.
    """
    transcription_service = TranscriptionService()
    mapping_service = SpeakerMappingService()

    try:
        # Validate speaker membership if speaker_user_id provided
        if speaker_user_id:
            is_participant = db.query(MeetingParticipant).filter(
                MeetingParticipant.meeting_id == meeting.public_id,
                MeetingParticipant.user_id == speaker_user_id,
            ).first()
            if not is_participant:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Speaker '{speaker_user_id}' is not an authorized participant in meeting '{meeting.public_id}'"
                )

        # Validate participant membership if participant_id provided
        if participant_id:
            from uuid import UUID
            try:
                guid_val = UUID(participant_id) if isinstance(participant_id, str) and len(participant_id) == 36 else participant_id
            except (ValueError, TypeError):
                guid_val = participant_id

            part_record = db.query(MeetingParticipant).filter(
                MeetingParticipant.meeting_id == meeting.public_id,
                (MeetingParticipant.id == guid_val) | (MeetingParticipant.id == str(participant_id)),
            ).first()
            if not part_record:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Participant '{participant_id}' does not belong to meeting '{meeting.public_id}'"
                )

        segments = transcription_service.get_transcript_segments(
            db,
            meeting.public_id,
            speaker_user_id=speaker_user_id,
            participant_id=participant_id,
        )

        # Get speaker mappings and user information
        speaker_mappings = mapping_service.get_speaker_mappings(db, meeting.public_id)
        speaker_map = {m["speaker_label"]: m["user_name"] for m in speaker_mappings}

        # Collect distinct speakers
        all_speakers = list(set(seg.speaker_label for seg in segments))

        return {
            "meeting_id": meeting.public_id,
            "total_segments": len(segments),
            "speakers": sorted(all_speakers),
            "segments": [
                {
                    "id": str(seg.id) if hasattr(seg, "id") and seg.id else None,
                    "segment_id": getattr(seg, "segment_id", None),
                    "recording_id": getattr(seg, "recording_id", None),
                    "speaker_label": seg.speaker_label,
                    "speaker_user_id": getattr(seg, "speaker_user_id", None) or seg.user_id,
                    "user_id": seg.user_id or getattr(seg, "speaker_user_id", None),
                    "participant_id": str(seg.participant_id) if getattr(seg, "participant_id", None) else None,
                    "attribution_status": getattr(seg, "attribution_status", "unknown"),
                    "start_time": seg.start_time,
                    "end_time": seg.end_time,
                    "text": seg.text,
                    "translated_text": getattr(seg, "translated_text", None),
                    "language": seg.language,
                    "confidence": seg.confidence,
                    "words": getattr(seg, "words", None),
                    "user_name": speaker_map.get(seg.speaker_label),
                    "speaker_confirmed": seg.speaker_confirmed,
                    "processing_metadata": getattr(seg, "processing_metadata", None),
                }
                for seg in segments
            ]
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/meetings/{meeting_id}/speakers/{speaker_user_id}")
def get_speaker_transcript(
    meeting_id: str,
    speaker_user_id: str,
    meeting: Meeting = Depends(get_meeting_and_authorize),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Fetch transcript segments for a particular authorized speaker in that meeting.
    Validates both meeting access authorization and speaker membership.
    """
    return get_transcript(
        meeting_id=meeting_id,
        speaker_user_id=speaker_user_id,
        participant_id=None,
        meeting=meeting,
        current_user=current_user,
        db=db,
    )


@router.get("/meetings/{meeting_id}/status")
def get_transcription_status(
    meeting_id: str,
    meeting: Meeting = Depends(get_meeting_and_authorize),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get transcription status for an authorized meeting.

    Returns processing status, error information, and segment count.
    """
    transcription_service = TranscriptionService()

    try:
        status_info = transcription_service.get_transcription_status(db, meeting.public_id)
        return status_info
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post(
    "/meetings/{meeting_id}/participants/{participant_id}/audio-stream",
    response_model=List[TranscriptSegmentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def process_participant_audio_stream(
    meeting_id: str,
    participant_id: str,
    file: UploadFile = File(...),
    start_offset: float = Form(default=0.0),
    end_offset: Optional[float] = Form(default=None),
    sequence_number: Optional[int] = Form(default=None),
    chunk_id: Optional[str] = Form(default=None),
    sample_rate: Optional[int] = Form(default=16000),
    language: Optional[str] = Form(default=None),
    meeting: Meeting = Depends(get_meeting_and_authorize),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Direct in-memory participant audio processing endpoint.
    Processes an authenticated participant's short-lived audio buffer directly,
    attributing transcript segments directly to the speaker with accurate capture offsets
    and zero durable audio storage.
    """
    # Safe GUID resolution for participant_id across database dialects
    guid_val = participant_id
    try:
        import uuid
        guid_val = uuid.UUID(str(participant_id))
    except (ValueError, TypeError, AttributeError):
        pass

    participant = db.query(MeetingParticipant).filter(
        MeetingParticipant.meeting_id == meeting.public_id,
        (MeetingParticipant.id == guid_val) | (MeetingParticipant.id == str(participant_id)),
    ).first()
    if not participant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Participant {participant_id} not found in meeting {meeting.public_id}",
        )

    # Strict Authorization: caller MUST match the participant's authenticated user identity.
    # A host or other participant CANNOT forge or submit audio on behalf of another user.
    if participant.user_id != current_user.public_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to submit audio stream for this participant: caller identity does not match participant",
        )

    # Server-side validation of capture timing offsets and sequence numbers
    if math.isnan(start_offset) or math.isinf(start_offset) or start_offset < 0.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_offset must be a non-negative finite number",
        )
    if start_offset > 86400.0:  # Max 24 hours meeting
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_offset exceeds reasonable meeting bounds (maximum 24 hours)",
        )

    if sequence_number is not None and sequence_number < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sequence_number must be non-negative",
        )

    if chunk_id is not None and len(chunk_id) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="chunk_id exceeds maximum allowed length of 128 characters",
        )

    if sample_rate is not None and (sample_rate < 8000 or sample_rate > 192000):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sample_rate must be between 8000 and 192000 Hz",
        )

    if end_offset is not None:
        if math.isnan(end_offset) or math.isinf(end_offset) or end_offset < start_offset:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="end_offset cannot be less than start_offset and must be a finite number",
            )
        if (end_offset - start_offset) > 300.0:  # 5 minutes chunk maximum
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Audio chunk duration exceeds maximum allowed limit of 300 seconds",
            )

    content = await file.read()
    if not content or len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio stream content is empty",
        )

    if len(content) > MAX_AUDIO_CHUNK_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Audio chunk exceeds maximum allowed size of 25MB ({len(content)} bytes)",
        )

    # Inspect audio frames, validate WAV structure, and calculate duration
    audio_duration = 0.0
    detected_rate = sample_rate or 16000
    frame_count = 0

    is_wav = content.startswith(b"RIFF")
    if is_wav:
        if len(content) < 44:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Audio chunk too small to be a valid WAV file",
            )
        try:
            with wave.open(io.BytesIO(content), "rb") as wf:
                framerate = wf.getframerate()
                n_frames = wf.getnframes()
                if framerate <= 0:
                    raise wave.Error("Invalid framerate in WAV header")
                detected_rate = framerate
                frame_count = n_frames
                audio_duration = round(n_frames / float(framerate), 3)
        except (wave.Error, EOFError) as wave_err:
            import logging
            logging.getLogger(__name__).warning(
                f"[AUDIO_VALIDATION_WARN] Malformed WAV file rejected for meeting {meeting.public_id}, "
                f"participant {participant_id}: {wave_err}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Malformed or corrupted WAV audio file: {wave_err}",
            )
    else:
        if sample_rate and sample_rate > 0:
            frame_count = len(content) // 2
            audio_duration = round(frame_count / float(sample_rate), 3)

    if audio_duration > 300.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio chunk duration exceeds maximum allowed limit of 300 seconds",
        )
    if (start_offset + audio_duration) > 86400.0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio chunk end offset exceeds maximum meeting bounds (24 hours)",
        )

    resolved_end_offset = end_offset
    if resolved_end_offset is None and audio_duration > 0.0:
        resolved_end_offset = round(start_offset + audio_duration, 3)

    # Stage 4: Update status to processing on first accepted chunk if pending
    if meeting.transcription_status == "pending":
        meeting.transcription_status = "processing"
        try:
            db.commit()
        except Exception:
            db.rollback()

    transcription_service = TranscriptionService()
    try:
        segments = transcription_service.transcribe_participant_audio_chunk(
            db=db,
            meeting=meeting,
            participant=participant,
            audio_bytes=content,
            language=language,
            start_offset=start_offset,
            end_offset=resolved_end_offset,
            sequence_number=sequence_number,
            chunk_id=chunk_id,
            sample_rate=detected_rate,
            frame_count=frame_count,
            chunk_duration=audio_duration,
        )
    except HTTPException:
        raise
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(
            f"[AUDIO_STREAM_ERROR] Participant audio stream transcription failed for meeting {meeting.public_id}, "
            f"participant {participant_id}: {exc}"
        )
        try:
            # Stage 4: Retain partial status if valid existing segments exist so existing data is not masked
            existing_seg_count = db.query(TranscriptSegment).filter(
                TranscriptSegment.meeting_id == meeting.public_id
            ).count()
            if existing_seg_count > 0:
                meeting.transcription_status = "partial"
            else:
                meeting.transcription_status = "failed"
            meeting.transcription_error = str(exc)
            db.commit()
        except Exception as status_err:
            db.rollback()
            logging.getLogger(__name__).warning(f"Could not persist transcription error status: {status_err}")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Participant audio stream transcription failed: {exc}",
        )

    return [
        TranscriptSegmentResponse(
            id=str(s.id),
            segment_id=s.segment_id,
            speaker_label=s.speaker_label,
            user_id=s.user_id,
            speaker_user_id=s.speaker_user_id,
            participant_id=str(s.participant_id) if s.participant_id else None,
            attribution_status=s.attribution_status,
            start_time=s.start_time,
            end_time=s.end_time,
            text=s.text,
            language=s.language,
            confidence=s.confidence,
            words=s.words,
            processing_metadata=s.processing_metadata,
        )
        for s in segments
    ]


@router.post("/meetings/{meeting_id}/upload")
async def upload_recording(
    meeting_id: str,
    file: UploadFile = File(...),
    language: Optional[str] = None,
    meeting: Meeting = Depends(require_meeting_host),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upload meeting recording for transcription (Host only).

    Accepts audio file and submits it for async transcription processing.
    Supported formats: wav, mp3, m4a, flac, ogg
    """
    # Validate file type
    allowed_extensions = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}
    file_ext = os.path.splitext(file.filename or "")[1].lower()

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
        )

    # Save uploaded file to dedicated temporary audio directory
    temp_file_path = None
    try:
        content = await file.read()
        if not content or len(content) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded recording file is empty",
            )

        if len(content) > settings.MAX_RECORDING_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Recording file exceeds maximum allowed size ({len(content)} > {settings.MAX_RECORDING_UPLOAD_BYTES} bytes)",
            )

        created_file = create_temp_audio_file(
            suffix=f".{file_ext}",
            prefix="recording_",
            meeting_id=meeting.public_id,
            content=content,
        )
        temp_file_path = str(created_file)

        # Update meeting with recording URL
        meeting.recording_url = temp_file_path
        meeting.transcription_status = "queued"
        meeting.transcription_error = None
        db.commit()

        # Submit to transcription worker
        job_submitted = submit_transcription_job(
            meeting_id=meeting.public_id,
            audio_path=temp_file_path,
            language=language
        )

        if not job_submitted:
            if temp_file_path:
                safe_delete_temp_file(temp_file_path, reason="job_submission_failed")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to submit transcription job"
            )

        return {
            "message": "Recording uploaded and queued for transcription",
            "meeting_id": meeting.public_id,
            "status": "queued"
        }

    except HTTPException:
        if temp_file_path:
            safe_delete_temp_file(temp_file_path, reason="upload_http_error")
        raise
    except Exception as e:
        if temp_file_path:
            safe_delete_temp_file(temp_file_path, reason="upload_exception")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process upload: {str(e)}"
        )


@router.delete("/meetings/{meeting_id}")
def delete_transcript(
    meeting_id: str,
    meeting: Meeting = Depends(require_meeting_host),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete transcript segments for a meeting (host only).

    This does not delete the meeting itself, only the transcript data.
    """
    try:
        # Delete all transcript segments for this meeting
        deleted_count = db.query(TranscriptSegment).filter(
            (TranscriptSegment.meeting_id == meeting.public_id) | (TranscriptSegment.meeting_id == str(meeting.id))
        ).delete(synchronize_session=False)

        # Reset transcription status
        meeting.transcription_status = "pending"
        meeting.transcription_error = None
        db.commit()

        return {
            "message": f"Deleted {deleted_count} transcript segments",
            "meeting_id": meeting.public_id
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
