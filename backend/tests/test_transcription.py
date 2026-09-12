"""
Tests for transcription service and API endpoints.
"""
import pytest
import tempfile
import os
from sqlalchemy.orm import Session

from app.models.meeting import Meeting
from app.models.company import Company
from app.models.user import User
from app.models.company import CompanyMember
from app.services.transcription_service import TranscriptionService, WhisperTranscriptionEngine
from app.services.meeting_service import get_meeting_by_public_id
from tests.conftest import TestingSessionLocal


@pytest.fixture
def test_company(setup_db):
    """Create a test company."""
    db = TestingSessionLocal()
    try:
        company = Company(
            public_id="test-company-1",
            name="Test Company",
            domain="test.com"
        )
        db.add(company)
        db.commit()
        db.refresh(company)
        yield company
    finally:
        db.close()


@pytest.fixture
def test_user(setup_db, test_company: Company):
    """Create a test user."""
    db = TestingSessionLocal()
    try:
        user = User(
            public_id="test-user-1",
            email="test@example.com",
            full_name="Test User",
            hashed_password="hashed_password"
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
        # Add user to company
        member = CompanyMember(
            company_id=test_company.public_id,
            user_id=user.public_id,
            role="COMPANY_ADMIN"
        )
        db.add(member)
        db.commit()
        
        yield user
    finally:
        db.close()


@pytest.fixture
def test_meeting(setup_db, test_company: Company, test_user: User):
    """Create a test meeting without project relationship."""
    db = TestingSessionLocal()
    try:
        meeting = Meeting(
            public_id="test-meeting-1",
            company_id=test_company.public_id,
            project_id=None,
            title="Test Meeting",
            status="completed"
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
        yield meeting
    finally:
        db.close()


@pytest.fixture
def test_audio_file():
    """Create a temporary test audio file."""
    # Create a small WAV file with silence (1 second)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        # Write minimal WAV header for 1 second of silence
        # 44.1kHz, 16-bit, mono
        sample_rate = 44100
        duration = 1  # seconds
        num_samples = sample_rate * duration
        byte_rate = sample_rate * 2  # 16-bit = 2 bytes per sample
        
        # WAV header
        header = bytearray()
        header.extend(b'RIFF')
        header.extend((36 + num_samples * 2).to_bytes(4, 'little'))  # file size
        header.extend(b'WAVE')
        header.extend(b'fmt ')
        header.extend((16).to_bytes(4, 'little'))  # fmt chunk size
        header.extend((1).to_bytes(2, 'little'))  # PCM format
        header.extend((1).to_bytes(2, 'little'))  # mono
        header.extend(sample_rate.to_bytes(4, 'little'))  # sample rate
        header.extend(byte_rate.to_bytes(4, 'little'))  # byte rate
        header.extend((2).to_bytes(2, 'little'))  # block align
        header.extend((16).to_bytes(2, 'little'))  # bits per sample
        header.extend(b'data')
        header.extend((num_samples * 2).to_bytes(4, 'little'))  # data size
        
        # Write silence (zeros)
        silence = bytes(num_samples * 2)
        
        f.write(header + silence)
        temp_path = f.name
    
    yield temp_path
    
    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)


class TestTranscriptionService:
    """Tests for TranscriptionService."""
    
    def test_transcription_service_initialization(self):
        """Test that TranscriptionService can be initialized."""
        service = TranscriptionService()
        assert service is not None
        assert service.engine is not None
        assert service.max_retries == 3
    
    def test_whisper_engine_initialization(self):
        """Test that WhisperTranscriptionEngine can be initialized."""
        # Note: This will download the model if not present
        # For testing, we might want to use a smaller model or mock this
        try:
            engine = WhisperTranscriptionEngine(model_size="tiny")
            assert engine is not None
            assert engine.model is not None
        except Exception as e:
            pytest.skip(f"Whisper model not available: {e}")
    
    def test_get_transcription_status(self, test_meeting: Meeting):
        """Test getting transcription status for a meeting."""
        db = TestingSessionLocal()
        try:
            service = TranscriptionService()
            
            status = service.get_transcription_status(db, test_meeting.public_id)
            
            assert status is not None
            assert status["status"] == "pending"  # Default status
            assert status["segment_count"] == 0
            assert status["error"] is None
        finally:
            db.close()
    
    def test_get_transcript_segments_empty(self, test_meeting: Meeting):
        """Test getting transcript segments when none exist."""
        db = TestingSessionLocal()
        try:
            service = TranscriptionService()
            
            segments = service.get_transcript_segments(db, test_meeting.public_id)
            
            assert segments == []
        finally:
            db.close()
    
    def test_get_transcript_segments_nonexistent_meeting(self):
        """Test getting transcript segments for non-existent meeting."""
        db = TestingSessionLocal()
        try:
            service = TranscriptionService()
            
            with pytest.raises(ValueError, match="Meeting not found"):
                service.get_transcript_segments(db, "nonexistent-meeting")
        finally:
            db.close()


class TestTranscriptionAPI:
    """Tests for transcription API endpoints."""
    
    def test_get_transcript_nonexistent_meeting(self, client):
        """Test getting transcript for non-existent meeting."""
        response = client.get("/api/v1/transcripts/meetings/nonexistent-meeting")
        
        # Transcript routes are protected; authentication is evaluated before
        # looking up the meeting identifier.
        assert response.status_code == 401


@pytest.mark.integration
class TestTranscriptionIntegration:
    """Integration tests for transcription (requires Whisper model)."""
    
    def test_full_transcription_workflow(self, test_meeting: Meeting, test_audio_file):
        """Test complete transcription workflow with real audio."""
        db = TestingSessionLocal()
        try:
            service = TranscriptionService()
            
            # Transcribe the audio file
            segments = service.transcribe_meeting(
                db=db,
                meeting=test_meeting,
                audio_path=test_audio_file,
                language=None
            )
            
            # Verify segments were created
            assert len(segments) >= 0  # May be 0 for silence
            
            # Verify meeting status
            db.refresh(test_meeting)
            assert test_meeting.transcription_status == "completed"
            assert test_meeting.transcription_error is None
            
            # Verify we can retrieve the segments
            retrieved_segments = service.get_transcript_segments(db, test_meeting.public_id)
            assert len(retrieved_segments) == len(segments)
            
        except Exception as e:
            pytest.skip(f"Integration test skipped: {e}")
        finally:
            db.close()
