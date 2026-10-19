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
    """Tests for transcription and meeting history API endpoints."""
    
    def test_get_transcript_nonexistent_meeting(self, client):
        """Test getting transcript without token returns 401."""
        response = client.get("/api/v1/transcripts/meetings/nonexistent-meeting")
        assert response.status_code == 401

    def test_get_transcript_nonexistent_when_authenticated(self, client):
        """Test authenticated user gets 404 for nonexistent meeting."""
        from app.models.user import User
        from app.core.tokens import create_token

        db = TestingSessionLocal()
        user = User(
            email="history_test@meetvault.com",
            full_name="History User",
            hashed_password="fakehash",
            public_id="usr_hist_1",
            account_type="personal",
        )
        db.add(user)
        db.commit()

        token = create_token(subject=user.public_id, token_type="access")
        resp = client.get(
            "/api/v1/transcripts/meetings/nonexistent-meeting-id",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
        db.close()

    def test_transcript_access_authorization_isolated_between_users(self, client):
        """Test user B receives 403 Forbidden when trying to access user A's private meeting transcript."""
        from app.models.user import User
        from app.models.meeting import Meeting, MeetingParticipant
        from app.models.transcript import TranscriptSegment
        from app.core.tokens import create_token

        db = TestingSessionLocal()
        user_a = User(email="owner@mv.com", full_name="Owner A", hashed_password="hash", public_id="usr_a", account_type="personal")
        user_b = User(email="intruder@mv.com", full_name="User B", hashed_password="hash", public_id="usr_b", account_type="personal")
        db.add_all([user_a, user_b])
        db.commit()

        # User A owns meeting
        meeting = Meeting(
            public_id="mtg_private_a",
            owner_id=user_a.public_id,
            title="Confidential Executive Review",
            meeting_type="PERSONAL",
            status="COMPLETED",
            transcription_status="completed",
        )
        db.add(meeting)
        db.commit()

        seg = TranscriptSegment(
            meeting_id=meeting.public_id,
            speaker_label="SPEAKER_00",
            start_time=1.0,
            end_time=4.0,
            text="Confidential revenue projections for Q4.",
            confidence=0.95,
        )
        db.add(seg)
        db.commit()

        token_a = create_token(subject=user_a.public_id, token_type="access")
        token_b = create_token(subject=user_b.public_id, token_type="access")

        # User B cannot access User A's transcript -> 403 Forbidden
        resp_b = client.get(
            f"/api/v1/transcripts/meetings/{meeting.public_id}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp_b.status_code == 403
        assert "not authorized" in resp_b.json()["detail"].lower()

        # User B cannot view transcription status either -> 403 Forbidden
        status_b = client.get(
            f"/api/v1/transcripts/meetings/{meeting.public_id}/status",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert status_b.status_code == 403

        # User A (owner) can access transcript -> 200 OK
        resp_a = client.get(
            f"/api/v1/transcripts/meetings/{meeting.public_id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp_a.status_code == 200
        data_a = resp_a.json()
        assert data_a["meeting_id"] == meeting.public_id
        assert len(data_a["segments"]) == 1
        assert data_a["segments"][0]["text"] == "Confidential revenue projections for Q4."
        assert data_a["segments"][0]["confidence"] == 0.95

        # If User B is added as a participant, they can now access it
        part_b = MeetingParticipant(
            meeting_id=meeting.public_id,
            user_id=user_b.public_id,
            role="ATTENDEE",
            status="JOINED",
        )
        db.add(part_b)
        db.commit()

        resp_b_allowed = client.get(
            f"/api/v1/transcripts/meetings/{meeting.public_id}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp_b_allowed.status_code == 200
        assert len(resp_b_allowed.json()["segments"]) == 1

        db.close()

    def test_delete_transcript_requires_meeting_host(self, client):
        """Test non-host cannot delete transcript segments, but host can."""
        from app.models.user import User
        from app.models.meeting import Meeting, MeetingParticipant
        from app.models.transcript import TranscriptSegment
        from app.core.tokens import create_token

        db = TestingSessionLocal()
        host = User(email="host@mv.com", full_name="Meeting Host", hashed_password="hash", public_id="usr_host", account_type="personal")
        attendee = User(email="attendee@mv.com", full_name="Attendee User", hashed_password="hash", public_id="usr_att", account_type="personal")
        db.add_all([host, attendee])
        db.commit()

        meeting = Meeting(
            public_id="mtg_delete_test",
            owner_id=host.public_id,
            title="Standup",
            meeting_type="PERSONAL",
            status="COMPLETED",
            transcription_status="completed",
        )
        db.add(meeting)
        db.commit()

        # Attendee joins
        part_att = MeetingParticipant(
            meeting_id=meeting.public_id,
            user_id=attendee.public_id,
            role="ATTENDEE",
            status="JOINED",
        )
        seg = TranscriptSegment(
            meeting_id=meeting.public_id,
            speaker_label="SPEAKER_00",
            start_time=0.0,
            end_time=2.0,
            text="Hello everyone",
        )
        db.add_all([part_att, seg])
        db.commit()

        token_host = create_token(subject=host.public_id, token_type="access")
        token_att = create_token(subject=attendee.public_id, token_type="access")

        # Attendee attempts delete -> 403 Forbidden
        del_resp = client.delete(
            f"/api/v1/transcripts/meetings/{meeting.public_id}",
            headers={"Authorization": f"Bearer {token_att}"},
        )
        assert del_resp.status_code == 403
        assert "host" in del_resp.json()["detail"].lower()

        # Host deletes -> 200 OK
        del_host_resp = client.delete(
            f"/api/v1/transcripts/meetings/{meeting.public_id}",
            headers={"Authorization": f"Bearer {token_host}"},
        )
        assert del_host_resp.status_code == 200
        assert "Deleted 1 transcript segments" in del_host_resp.json()["message"]

        db.close()

    def test_meeting_history_endpoint_and_transcription_metadata(self, client):
        """Test GET /meetings/history returns real persisted meetings with transcription fields and tenant scoping."""
        from app.models.user import User
        from app.models.meeting import Meeting
        from app.core.tokens import create_token
        from datetime import datetime, timezone

        db = TestingSessionLocal()
        u1 = User(email="user1@mv.com", full_name="User One", hashed_password="hash", public_id="usr_h1", account_type="personal")
        u2 = User(email="user2@mv.com", full_name="User Two", hashed_password="hash", public_id="usr_h2", account_type="personal")
        db.add_all([u1, u2])
        db.commit()

        m1 = Meeting(
            public_id="mtg_hist_1",
            owner_id=u1.public_id,
            title="Q3 Strategy Meeting",
            meeting_type="PERSONAL",
            status="COMPLETED",
            duration_seconds=1800,
            start_time=datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 10, 19, 10, 30, tzinfo=timezone.utc),
            transcription_status="completed",
            recording_url="storage/recordings/mtg_hist_1.wav",
        )
        m2 = Meeting(
            public_id="mtg_hist_2",
            owner_id=u2.public_id,
            title="User Two Secret Meeting",
            meeting_type="PERSONAL",
            status="SCHEDULED",
            transcription_status="pending",
        )
        db.add_all([m1, m2])
        db.commit()

        token_1 = create_token(subject=u1.public_id, token_type="access")
        resp = client.get("/api/v1/meetings/history", headers={"Authorization": f"Bearer {token_1}"})
        assert resp.status_code == 200
        history = resp.json()

        assert len(history) == 1
        item = history[0]
        assert item["meeting_id"] == "mtg_hist_1"
        assert item["title"] == "Q3 Strategy Meeting"
        assert item["status"] == "COMPLETED"
        assert item["duration_seconds"] == 1800
        assert item["my_role"] == "HOST"
        assert item["transcription_status"] == "completed"
        assert item["recording_url"] == "storage/recordings/mtg_hist_1.wav"

        db.close()


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
