from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
import os
import tempfile

from app.db.session import get_db
from app.core.dependencies import get_current_user
from app.core.meeting_dependencies import get_meeting_and_authorize, require_meeting_host
from app.models.user import User
from app.models.meeting import Meeting
from app.models.transcript import TranscriptSegment
from app.services.transcription_service import TranscriptionService
from app.workers import submit_transcription_job

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


@router.get("/meetings/{meeting_id}")
def get_transcript(
    meeting_id: str,
    meeting: Meeting = Depends(get_meeting_and_authorize),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get transcript segments for an authorized meeting.
    
    Returns timestamped transcript segments ordered by start time with speaker mapping.
    """
    from app.services.speaker_mapping_service import SpeakerMappingService
    
    transcription_service = TranscriptionService()
    mapping_service = SpeakerMappingService()
    
    try:
        segments = transcription_service.get_transcript_segments(db, meeting.public_id)
        
        # Get speaker mappings
        speaker_mappings = mapping_service.get_speaker_mappings(db, meeting.public_id)
        speaker_map = {m["speaker_label"]: m["user_name"] for m in speaker_mappings}
        
        return {
            "meeting_id": meeting.public_id,
            "segments": [
                {
                    "segment_id": getattr(seg, "segment_id", None),
                    "recording_id": getattr(seg, "recording_id", None),
                    "speaker_label": seg.speaker_label,
                    "start_time": seg.start_time,
                    "end_time": seg.end_time,
                    "text": seg.text,
                    "translated_text": getattr(seg, "translated_text", None),
                    "language": seg.language,
                    "confidence": seg.confidence,
                    "words": getattr(seg, "words", None),
                    "user_name": speaker_map.get(seg.speaker_label),
                    "speaker_confirmed": seg.speaker_confirmed,
                }
                for seg in segments
            ]
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


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


@router.post("/meetings/{meeting_id}/upload")
async def upload_recording(
    meeting_id: str,
    file: UploadFile = File(...),
    language: Optional[str] = None,
    meeting: Meeting = Depends(get_meeting_and_authorize),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Upload meeting recording for transcription.
    
    Accepts audio file and submits it for async transcription processing.
    Supported formats: wav, mp3, m4a, flac, ogg
    """
    # Validate file type
    allowed_extensions = {".wav", ".mp3", ".m4a", ".flac", ".ogg"}
    file_ext = os.path.splitext(file.filename)[1].lower()
    
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
        )
    
    # Save uploaded file to temporary location
    try:
        # Create temp directory if it doesn't exist
        temp_dir = tempfile.gettempdir()
        temp_file_path = os.path.join(temp_dir, f"recording_{meeting.public_id}_{file.filename}")
        
        # Write uploaded file
        with open(temp_file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
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
        raise
    except Exception as e:
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