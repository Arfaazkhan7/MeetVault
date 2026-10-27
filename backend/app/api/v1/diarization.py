from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional, List

from app.db.session import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.models.meeting import Meeting
from app.services.diarization_service import DiarizationService, MockDiarizationEngine
from app.services.speaker_mapping_service import SpeakerMappingService
from app.services.meeting_service import get_meeting_by_public_id

router = APIRouter(prefix="/diarization", tags=["diarization"])


@router.post("/meetings/{meeting_id}/diarize")
def diarize_meeting(
    meeting_id: str,
    num_speakers: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Perform speaker diarization on meeting audio.
    
    Analyzes the audio file to identify different speakers and their segments.
    """
    meeting = get_meeting_by_public_id(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    
    if not meeting.recording_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No recording available for diarization"
        )
    
    try:
        # Use mock engine for development, real Pyannote for production
        diarization_service = DiarizationService(engine=MockDiarizationEngine())
        
        # Perform diarization
        speaker_segments = diarization_service.diarize_meeting(
            meeting.recording_url,
            num_speakers
        )
        
        # Normalize speaker labels
        normalized_segments = diarization_service.normalize_speaker_labels(speaker_segments)
        
        # Create speaker mappings
        speaker_labels = list(set(seg["speaker"] for seg in normalized_segments))
        mapping_service = SpeakerMappingService()
        mappings = mapping_service.create_speaker_mappings(db, meeting, speaker_labels)
        
        return {
            "meeting_id": meeting_id,
            "speaker_segments": normalized_segments,
            "speaker_mappings": mappings,
            "num_speakers": len(speaker_labels)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Diarization failed: {str(e)}"
        )


from app.core.meeting_dependencies import get_meeting_and_authorize

@router.get("/meetings/{meeting_id}/speaker-mappings")
def get_speaker_mappings(
    meeting_id: str,
    meeting: Meeting = Depends(get_meeting_and_authorize),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all speaker mappings for an authorized meeting."""
    mapping_service = SpeakerMappingService()
    mappings = mapping_service.get_speaker_mappings(db, meeting.public_id)
    
    return {
        "meeting_id": meeting.public_id,
        "mappings": mappings
    }


@router.put("/meetings/{meeting_id}/speaker-mappings/{speaker_label}")
def update_speaker_mapping(
    meeting_id: str,
    speaker_label: str,
    user_id: Optional[str] = None,
    is_confirmed: bool = False,
    notes: Optional[str] = None,
    meeting: Meeting = Depends(get_meeting_and_authorize),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update a speaker mapping for an authorized meeting.
    Validates that user_id is an authorized participant in the meeting.
    """
    mapping_service = SpeakerMappingService()
    
    try:
        mapping = mapping_service.update_speaker_mapping(
            db=db,
            meeting_id=meeting.public_id,
            speaker_label=speaker_label,
            user_id=user_id,
            is_confirmed=is_confirmed,
            notes=notes
        )
        
        return {
            "meeting_id": meeting.public_id,
            "speaker_label": speaker_label,
            "user_id": mapping.user_id,
            "is_confirmed": mapping.is_confirmed
        }
        
    except ValueError as e:
        status_code = status.HTTP_400_BAD_REQUEST if "not an authorized participant" in str(e) else status.HTTP_404_NOT_FOUND
        raise HTTPException(
            status_code=status_code,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/meetings/{meeting_id}/speaker-mappings/{speaker_label}/confirm")
def confirm_speaker_mapping(
    meeting_id: str,
    speaker_label: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Confirm a speaker mapping."""
    meeting = get_meeting_by_public_id(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    
    mapping_service = SpeakerMappingService()
    
    try:
        mapping = mapping_service.confirm_speaker_mapping(db, meeting_id, speaker_label)
        
        return {
            "meeting_id": meeting_id,
            "speaker_label": speaker_label,
            "is_confirmed": mapping.is_confirmed
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/meetings/{meeting_id}/available-users")
def get_available_users(
    meeting_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get available users for speaker mapping (meeting participants)."""
    meeting = get_meeting_by_public_id(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    
    mapping_service = SpeakerMappingService()
    users = mapping_service.get_available_users(db, meeting_id)
    
    return {
        "meeting_id": meeting_id,
        "users": users
    }


@router.post("/meetings/{meeting_id}/auto-map-speakers")
def auto_map_speakers(
    meeting_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Attempt to auto-map speakers to participants.
    
    Uses heuristics to suggest speaker-to-user mappings.
    """
    meeting = get_meeting_by_public_id(db, meeting_id)
    if not meeting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    
    mapping_service = SpeakerMappingService()
    
    try:
        suggestions = mapping_service.auto_map_speakers(db, meeting_id)
        
        return {
            "meeting_id": meeting_id,
            "suggestions": suggestions
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )