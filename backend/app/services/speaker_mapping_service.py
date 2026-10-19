import logging
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session

from app.models.speaker_mapping import SpeakerMapping
from app.models.transcript import TranscriptSegment
from app.models.user import User
from app.models.meeting import Meeting

logger = logging.getLogger(__name__)


class SpeakerMappingService:
    """Service for managing speaker mappings (SPEAKER_XX → USR-XXXX)."""
    
    def __init__(self):
        """Initialize speaker mapping service."""
        pass
    
    def create_speaker_mappings(
        self,
        db: Session,
        meeting: Meeting,
        speaker_labels: List[str]
    ) -> Dict[str, str]:
        """
        Create initial speaker mappings for a meeting while preserving existing confirmed mappings.
        
        Args:
            db: Database session
            meeting: Meeting instance
            speaker_labels: List of speaker labels (SPEAKER_00, SPEAKER_01, etc.)
        
        Returns:
            Dictionary of speaker labels to user IDs
        """
        existing = db.query(SpeakerMapping).filter(
            SpeakerMapping.meeting_id == meeting.public_id
        ).all()
        existing_map = {m.speaker_label: m for m in existing}
        
        mappings = {}
        for speaker_label in speaker_labels:
            if speaker_label == "SPEAKER_UNKNOWN":
                continue
            
            if speaker_label in existing_map:
                # Preserve existing mapping, especially if user confirmed it
                mappings[speaker_label] = existing_map[speaker_label].user_id or ""
                continue
            
            mapping = SpeakerMapping(
                meeting_id=meeting.public_id,
                speaker_label=speaker_label,
                user_id=None,  # Initially unmapped
                is_confirmed=False,
                confidence="medium"
            )
            db.add(mapping)
            mappings[speaker_label] = ""  # Empty = unmapped
        
        # Remove orphaned unconfirmed mappings for labels that no longer exist
        for label, m in existing_map.items():
            if label not in speaker_labels and not m.is_confirmed:
                db.delete(m)
        
        db.commit()
        return mappings
    
    def get_speaker_mappings(
        self,
        db: Session,
        meeting_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get all speaker mappings for a meeting.
        
        Args:
            db: Database session
            meeting_id: Meeting public ID
        
        Returns:
            List of speaker mappings with user information
        """
        mappings = db.query(SpeakerMapping).filter(
            SpeakerMapping.meeting_id == meeting_id
        ).all()
        
        result = []
        for mapping in mappings:
            user = None
            if mapping.user_id:
                user = db.query(User).filter(
                    User.public_id == mapping.user_id
                ).first()
            
            result.append({
                "speaker_label": mapping.speaker_label,
                "user_id": mapping.user_id,
                "user_name": user.full_name if user else None,
                "user_email": user.email if user else None,
                "is_confirmed": mapping.is_confirmed,
                "confidence": mapping.confidence,
                "notes": mapping.notes
            })
        
        return result
    
    def update_speaker_mapping(
        self,
        db: Session,
        meeting_id: str,
        speaker_label: str,
        user_id: Optional[str],
        is_confirmed: bool = False,
        notes: Optional[str] = None
    ) -> SpeakerMapping:
        """
        Update a speaker mapping.
        
        Args:
            db: Database session
            meeting_id: Meeting public ID
            speaker_label: Speaker label (SPEAKER_00, etc.)
            user_id: User public ID or None to unmap
            is_confirmed: Whether mapping is confirmed
            notes: Additional notes
        
        Returns:
            Updated speaker mapping
        """
        mapping = db.query(SpeakerMapping).filter(
            SpeakerMapping.meeting_id == meeting_id,
            SpeakerMapping.speaker_label == speaker_label
        ).first()
        
        if not mapping:
            raise ValueError(f"Speaker mapping not found: {speaker_label}")
        
        mapping.user_id = user_id
        mapping.is_confirmed = is_confirmed
        if notes is not None:
            mapping.notes = notes
        
        db.commit()
        db.refresh(mapping)
        
        # Update transcript segments with user_id
        self._update_transcript_user_mapping(db, meeting_id, speaker_label, user_id)
        
        return mapping
    
    def _update_transcript_user_mapping(
        self,
        db: Session,
        meeting_id: str,
        speaker_label: str,
        user_id: Optional[str]
    ):
        """
        Update transcript segments, evidence, and AI entities with user mapping.
        """
        from app.models.evidence import Evidence
        from app.models.task import Task
        from app.models.decision import Decision
        from app.models.intelligence import Question, Risk, Commitment

        segments = db.query(TranscriptSegment).filter(
            TranscriptSegment.meeting_id == meeting_id,
            TranscriptSegment.speaker_label == speaker_label
        ).all()
        
        for segment in segments:
            segment.user_id = user_id
            if user_id:
                segment.speaker_confirmed = True
        
        # Propagate to Evidence
        evidences = db.query(Evidence).filter(
            Evidence.meeting_id == meeting_id,
            Evidence.speaker_label == speaker_label
        ).all()
        for ev in evidences:
            ev.user_id = user_id

        # Propagate to Tasks (Action Items)
        tasks = db.query(Task).filter(
            Task.meeting_id == meeting_id,
            Task.speaker_label == speaker_label
        ).all()
        for t in tasks:
            if user_id:
                t.assignee_id = user_id

        # Propagate to Decisions
        decisions = db.query(Decision).filter(
            Decision.meeting_id == meeting_id,
            Decision.speaker_label == speaker_label
        ).all()
        for d in decisions:
            if user_id:
                d.proposer_id = user_id

        # Propagate to Questions
        questions = db.query(Question).filter(
            Question.meeting_id == meeting_id,
            Question.asked_by_participant_id == speaker_label
        ).all()
        for q in questions:
            if user_id:
                q.asked_by_participant_id = user_id

        # Propagate to Commitments
        commitments = db.query(Commitment).filter(
            Commitment.meeting_id == meeting_id,
            Commitment.person == speaker_label
        ).all()
        for c in commitments:
            if user_id:
                c.participant_id = user_id

        db.commit()
    
    def auto_map_speakers(
        self,
        db: Session,
        meeting_id: str
    ) -> Dict[str, str]:
        """
        Attempt to auto-map speakers based on meeting participants.
        
        Args:
            db: Database session
            meeting_id: Meeting public ID
        
        Returns:
            Dictionary of suggested mappings
        """
        from app.models.meeting import MeetingParticipant
        
        # Get meeting participants
        participants = db.query(MeetingParticipant).filter(
            MeetingParticipant.meeting_id == meeting_id
        ).all()
        
        # Get speaker mappings
        mappings = db.query(SpeakerMapping).filter(
            SpeakerMapping.meeting_id == meeting_id
        ).all()
        
        suggestions = {}
        
        # Simple heuristic: map speakers to participants in order
        # In production, this could use voice profiles or other ML techniques
        for i, mapping in enumerate(sorted(mappings, key=lambda m: m.speaker_label)):
            if i < len(participants) and not mapping.is_confirmed:
                suggestions[mapping.speaker_label] = participants[i].user_id
        
        return suggestions
    
    def get_available_users(
        self,
        db: Session,
        meeting_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get available users for speaker mapping (meeting participants).
        
        Args:
            db: Database session
            meeting_id: Meeting public ID
        
        Returns:
            List of available users
        """
        from app.models.meeting import MeetingParticipant
        
        participants = db.query(MeetingParticipant).filter(
            MeetingParticipant.meeting_id == meeting_id
        ).all()
        
        user_ids = [p.user_id for p in participants]
        users = db.query(User).filter(User.public_id.in_(user_ids)).all()
        
        return [
            {
                "user_id": user.public_id,
                "full_name": user.full_name,
                "email": user.email
            }
            for user in users
        ]
    
    def confirm_speaker_mapping(
        self,
        db: Session,
        meeting_id: str,
        speaker_label: str
    ) -> SpeakerMapping:
        """
        Confirm a speaker mapping.
        
        Args:
            db: Database session
            meeting_id: Meeting public ID
            speaker_label: Speaker label
        
        Returns:
            Updated speaker mapping
        """
        mapping = db.query(SpeakerMapping).filter(
            SpeakerMapping.meeting_id == meeting_id,
            SpeakerMapping.speaker_label == speaker_label
        ).first()
        
        if not mapping:
            raise ValueError(f"Speaker mapping not found: {speaker_label}")
        
        mapping.is_confirmed = True
        db.commit()
        db.refresh(mapping)
        
        return mapping