import pytest
from sqlalchemy.orm import Session
from datetime import datetime
from app.services.diarization_service import (
    DiarizationService,
    MockDiarizationEngine,
    PyannoteDiarizationEngine
)
from app.services.speaker_mapping_service import SpeakerMappingService
from app.models.speaker_mapping import SpeakerMapping
from app.models.transcript import TranscriptSegment
from app.models.meeting import Meeting
from app.models.user import User
from tests.conftest import TestingSessionLocal


@pytest.fixture
def test_meeting(setup_db):
    """Create a test meeting."""
    db = TestingSessionLocal()
    try:
        meeting = Meeting(
            public_id="test-meeting-1",
            title="Test Meeting",
            description="Test Description",
            company_id="test-company",
            project_id="test-project",
            scheduled_start_time=datetime(2024, 1, 1, 10, 0, 0),
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
        yield meeting
    finally:
        db.close()


@pytest.fixture
def test_user(setup_db):
    """Create a test user."""
    db = TestingSessionLocal()
    try:
        user = User(
            public_id="test-user-1",
            full_name="Test User",
            email="test@example.com",
            hashed_password="hashed_password",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        yield user
    finally:
        db.close()


class TestDiarizationService:
    """Test cases for DiarizationService."""
    
    def test_diarization_service_initialization(self):
        """Test that DiarizationService can be initialized."""
        service = DiarizationService()
        assert service.engine is not None
        assert service.max_retries == 3
    
    def test_mock_diarization_engine(self):
        """Test mock diarization engine."""
        engine = MockDiarizationEngine()
        segments = engine.diarize("test_audio.wav")
        
        assert len(segments) > 0
        assert segments[0]["speaker"] == "SPEAKER_00"
        assert "start_time" in segments[0]
        assert "end_time" in segments[0]
    
    def test_normalize_speaker_labels(self):
        """Test speaker label normalization."""
        service = DiarizationService()
        
        segments = [
            {"speaker": "speaker_1", "start_time": 0, "end_time": 5},
            {"speaker": "speaker_2", "start_time": 5, "end_time": 10},
            {"speaker": "speaker_1", "start_time": 10, "end_time": 15},
        ]
        
        normalized = service.normalize_speaker_labels(segments)
        
        # Check that labels are normalized
        speakers = set(seg["speaker"] for seg in normalized)
        assert "SPEAKER_00" in speakers
        assert "SPEAKER_01" in speakers
        assert "speaker_1" not in speakers
        assert "speaker_2" not in speakers
    
    def test_find_dominant_speaker(self):
        """Test finding dominant speaker for a time interval."""
        service = DiarizationService()
        
        diarization_segments = [
            {"speaker": "SPEAKER_00", "start_time": 0, "end_time": 5},
            {"speaker": "SPEAKER_01", "start_time": 5, "end_time": 10},
        ]
        
        # Test case where transcript fully matches SPEAKER_00
        speaker = service._find_dominant_speaker(1, 4, diarization_segments)
        assert speaker == "SPEAKER_00"
        
        # Test case where transcript spans boundary
        speaker = service._find_dominant_speaker(4, 6, diarization_segments)
        # Should return the speaker with more overlap
        assert speaker in ["SPEAKER_00", "SPEAKER_01"]
    
    def test_align_transcript_with_speakers(self):
        """Test aligning transcript segments with speaker diarization."""
        service = DiarizationService()
        
        transcript_segments = [
            {"start_time": 1, "end_time": 4, "text": "Hello"},
            {"start_time": 6, "end_time": 9, "text": "World"},
        ]
        
        diarization_segments = [
            {"speaker": "SPEAKER_00", "start_time": 0, "end_time": 5},
            {"speaker": "SPEAKER_01", "start_time": 5, "end_time": 10},
        ]
        
        aligned = service.align_transcript_with_speakers(
            transcript_segments, diarization_segments
        )
        
        assert len(aligned) == 2
        assert aligned[0]["speaker_label"] == "SPEAKER_00"
        assert aligned[1]["speaker_label"] == "SPEAKER_01"
    
    def test_handle_overlapping_speech(self):
        """Test handling of overlapping speech."""
        service = DiarizationService()
        
        segments = [
            {"speaker": "SPEAKER_00", "start_time": 0, "end_time": 8},
            {"speaker": "SPEAKER_01", "start_time": 5, "end_time": 10},
        ]
        
        processed = service.handle_overlapping_speech(segments)
        
        # Should split overlapping segments
        assert len(processed) >= 2
        
        # Check that overlapping flag is set where appropriate
        overlapping_segments = [s for s in processed if s.get("overlapping")]
        assert len(overlapping_segments) > 0
    
    def test_create_speaker_mapping(self):
        """Test creating speaker mapping dictionary."""
        service = DiarizationService()
        
        segments = [
            {"speaker": "SPEAKER_00", "start_time": 0, "end_time": 5},
            {"speaker": "SPEAKER_01", "start_time": 5, "end_time": 10},
            {"speaker": "SPEAKER_UNKNOWN", "start_time": 10, "end_time": 15},
        ]
        
        mapping = service.create_speaker_mapping(segments)
        
        assert "SPEAKER_00" in mapping
        assert "SPEAKER_01" in mapping
        assert "SPEAKER_UNKNOWN" not in mapping  # Unknown speakers excluded
        assert mapping["SPEAKER_00"] == ""  # Unmapped initially


class TestSpeakerMappingService:
    """Test cases for SpeakerMappingService."""
    
    def test_create_speaker_mappings(self, test_meeting: Meeting):
        """Test creating speaker mappings for a meeting."""
        db = TestingSessionLocal()
        try:
            service = SpeakerMappingService()
            
            speaker_labels = ["SPEAKER_00", "SPEAKER_01"]
            mappings = service.create_speaker_mappings(db, test_meeting, speaker_labels)
            
            assert "SPEAKER_00" in mappings
            assert "SPEAKER_01" in mappings
            assert mappings["SPEAKER_00"] == ""  # Unmapped
            
            # Verify database entries
            db_mappings = db.query(SpeakerMapping).filter(
                SpeakerMapping.meeting_id == test_meeting.public_id
            ).all()
            
            assert len(db_mappings) == 2
        finally:
            db.close()
    
    def test_get_speaker_mappings(self, test_meeting: Meeting):
        """Test retrieving speaker mappings."""
        db = TestingSessionLocal()
        try:
            service = SpeakerMappingService()
            
            # Create mappings
            service.create_speaker_mappings(db, test_meeting, ["SPEAKER_00", "SPEAKER_01"])
            
            # Retrieve mappings
            mappings = service.get_speaker_mappings(db, test_meeting.public_id)
            
            assert len(mappings) == 2
            assert mappings[0]["speaker_label"] in ["SPEAKER_00", "SPEAKER_01"]
            assert mappings[0]["is_confirmed"] == False
        finally:
            db.close()
    
    def test_update_speaker_mapping(self, test_meeting: Meeting, test_user: User):
        """Test updating a speaker mapping."""
        from app.models.meeting import MeetingParticipant
        db = TestingSessionLocal()
        try:
            service = SpeakerMappingService()
            
            # Add participant
            participant = MeetingParticipant(
                meeting_id=test_meeting.public_id,
                user_id=test_user.public_id,
                role="participant"
            )
            db.add(participant)
            db.commit()

            # Create initial mappings
            service.create_speaker_mappings(db, test_meeting, ["SPEAKER_00"])
            
            # Update mapping
            updated = service.update_speaker_mapping(
                db, test_meeting.public_id, "SPEAKER_00", test_user.public_id, is_confirmed=True
            )
            
            assert updated.user_id == test_user.public_id
            assert updated.is_confirmed == True
        finally:
            db.close()
    
    def test_auto_map_speakers(self, test_meeting: Meeting, test_user: User):
        """Test auto-mapping speakers to participants."""
        from app.models.meeting import MeetingParticipant
        
        db = TestingSessionLocal()
        try:
            service = SpeakerMappingService()
            
            # Add participant
            participant = MeetingParticipant(
                meeting_id=test_meeting.public_id,
                user_id=test_user.public_id,
                role="participant"
            )
            db.add(participant)
            db.commit()
            
            # Create speaker mappings
            service.create_speaker_mappings(db, test_meeting, ["SPEAKER_00"])
            
            # Auto-map
            suggestions = service.auto_map_speakers(db, test_meeting.public_id)
            
            assert len(suggestions) > 0
            # Should suggest mapping participant to SPEAKER_00
        finally:
            db.close()
    
    def test_get_available_users(self, test_meeting: Meeting, test_user: User):
        """Test getting available users for mapping."""
        from app.models.meeting import MeetingParticipant
        
        db = TestingSessionLocal()
        try:
            service = SpeakerMappingService()
            
            # Add participant
            participant = MeetingParticipant(
                meeting_id=test_meeting.public_id,
                user_id=test_user.public_id,
                role="participant"
            )
            db.add(participant)
            db.commit()
            
            # Get available users
            users = service.get_available_users(db, test_meeting.public_id)
            
            assert len(users) == 1
            assert users[0]["user_id"] == test_user.public_id
            assert users[0]["full_name"] == test_user.full_name
        finally:
            db.close()
    
    def test_confirm_speaker_mapping(self, test_meeting: Meeting):
        """Test confirming a speaker mapping."""
        db = TestingSessionLocal()
        try:
            service = SpeakerMappingService()
            
            # Create mappings
            service.create_speaker_mappings(db, test_meeting, ["SPEAKER_00"])
            
            # Confirm mapping
            confirmed = service.confirm_speaker_mapping(db, test_meeting.public_id, "SPEAKER_00")
            
            assert confirmed.is_confirmed == True
        finally:
            db.close()


class TestDiarizationIntegration:
    """Integration tests for diarization workflow."""
    
    def test_diarization_workflow(self, test_meeting: Meeting):
        """Test complete diarization workflow."""
        db = TestingSessionLocal()
        try:
            diarization_service = DiarizationService()
            mapping_service = SpeakerMappingService()
            
            # Perform diarization (using mock)
            speaker_segments = diarization_service.diarize_meeting("test_audio.wav")
            
            # Normalize labels
            normalized_segments = diarization_service.normalize_speaker_labels(speaker_segments)
            
            # Create speaker mappings
            speaker_labels = list(set(seg["speaker"] for seg in normalized_segments))
            mappings = mapping_service.create_speaker_mappings(db, test_meeting, speaker_labels)
            
            # Verify
            assert len(normalized_segments) > 0
            assert len(mappings) > 0
            
            # Retrieve mappings
            retrieved_mappings = mapping_service.get_speaker_mappings(db, test_meeting.public_id)
            assert len(retrieved_mappings) == len(mappings)
        finally:
            db.close()
    
    def test_transcript_alignment_with_db(self, test_meeting: Meeting):
        """Test aligning transcript with database persistence."""
        db = TestingSessionLocal()
        try:
            diarization_service = DiarizationService()
            
            # Create transcript segments
            transcript_segments = [
                TranscriptSegment(
                    meeting_id=test_meeting.public_id,
                    speaker_label="UNKNOWN",
                    start_time=1.0,
                    end_time=4.0,
                    text="Hello world"
                )
            ]
            db.add_all(transcript_segments)
            db.commit()
            
            # Perform diarization
            diarization_segments = diarization_service.diarize_meeting("test_audio.wav")
            
            # Align
            aligned = diarization_service.align_transcript_with_speakers(
                [{"start_time": 1.0, "end_time": 4.0, "text": "Hello world"}],
                diarization_segments
            )
            
            assert len(aligned) == 1
            assert aligned[0]["speaker_label"] != "UNKNOWN"
        finally:
            db.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])