"""
Stage 4 Validation: Live Transcript Status Management & Lifecycle Tests.

Validates:
1. Initial status is 'pending' when meeting is created.
2. Accepts audio chunk -> transitions to 'processing' / 'partial' when segments saved.
3. Live meeting stays 'partial' across multiple chunks (never prematurely 'completed').
4. Meeting lifecycle completion (end_meeting) transitions 'partial' -> 'completed'.
5. Audio failure with existing segments preserves 'partial' status and segments without loss.
6. Audio failure with 0 segments marks 'failed'.
7. Status endpoint auto-resolves partial to completed if meeting is already COMPLETED.
"""
import io
import wave
import uuid
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.models.company import Company, CompanyMember
from app.models.meeting import Meeting, MeetingParticipant
from app.models.transcript import TranscriptSegment
from app.models.user import User
from app.core.roles import Role
from app.core.enums import MeetingRole, MeetingStatus, TranscriptionStatus, ParticipantStatus
from app.core.tokens import create_token
from tests.conftest import TestingSessionLocal

client = TestClient(app)


def _create_wav_bytes(duration_sec: float = 1.0, sample_rate: int = 16000) -> bytes:
    num_frames = int(duration_sec * sample_rate)
    pcm_data = b"\x00\x00" * num_frames
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


@pytest.fixture
def stage4_setup():
    db = TestingSessionLocal()
    comp_id = f"comp-s4-{uuid.uuid4().hex[:6]}"
    host_id = f"usr-host-{uuid.uuid4().hex[:6]}"
    mtg_id = f"mtg-s4-{uuid.uuid4().hex[:6]}"
    part_id = str(uuid.uuid4())

    company = Company(public_id=comp_id, name="Stage 4 Test Corp", workspace_code="S4-01")
    host = User(
        public_id=host_id,
        email=f"host-{uuid.uuid4().hex[:4]}@s4.com",
        full_name="Host User",
        hashed_password="hash",
        account_type="company",
    )
    db.add_all([company, host])
    db.flush()

    member = CompanyMember(user_id=host.public_id, company_id=company.public_id, role=Role.MEMBER.value)
    meeting = Meeting(
        public_id=mtg_id,
        company_id=comp_id,
        owner_id=host.public_id,
        title="Live Status Management Meeting",
        status=MeetingStatus.LIVE.value,
        transcription_status="pending",
    )
    participant = MeetingParticipant(
        id=part_id,
        meeting_id=mtg_id,
        user_id=host.public_id,
        display_name="Host User",
        role=MeetingRole.HOST.value,
        status=ParticipantStatus.JOINED.value,
        is_guest=False,
    )
    db.add_all([member, meeting, participant])
    db.commit()

    token = create_token(subject=host.public_id, token_type="access")
    db.close()

    return {
        "meeting_id": mtg_id,
        "participant_id": part_id,
        "host_id": host_id,
        "token": token,
    }


def test_initial_meeting_status_is_pending(stage4_setup):
    """Initial meeting transcription status is pending with 0 segments."""
    mtg_id = stage4_setup["meeting_id"]
    token = stage4_setup["token"]

    resp = client.get(
        f"/api/v1/transcripts/meetings/{mtg_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["segment_count"] == 0
    assert data["speaker_count"] == 0
    assert data["error"] is None


def test_first_chunk_transitions_to_partial(stage4_setup):
    """When the first audio chunk is processed, status becomes partial and not completed."""
    mtg_id = stage4_setup["meeting_id"]
    part_id = stage4_setup["participant_id"]
    token = stage4_setup["token"]
    wav_bytes = _create_wav_bytes(1.0)

    mock_result = {
        "segments": [{"start_time": 0.0, "end_time": 1.0, "text": "Hello world stage 4"}],
        "language": "en",
    }

    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", return_value=mock_result):
        resp = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk1.wav", wav_bytes, "audio/wav")},
            data={"start_offset": 0.0, "sequence_number": 0},
        )
        assert resp.status_code == 201
        assert len(resp.json()) == 1

    # Check status endpoint
    status_resp = client.get(
        f"/api/v1/transcripts/meetings/{mtg_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["status"] == "partial"
    assert status_data["segment_count"] == 1
    assert status_data["error"] is None


def test_multiple_chunks_preserve_partial_not_completed(stage4_setup):
    """A meeting with persisted segments remains partial until finalized, never premature completed."""
    mtg_id = stage4_setup["meeting_id"]
    part_id = stage4_setup["participant_id"]
    token = stage4_setup["token"]
    wav_bytes = _create_wav_bytes(1.0)

    mock_result_1 = {
        "segments": [{"start_time": 0.0, "end_time": 1.0, "text": "First chunk"}],
        "language": "en",
    }
    mock_result_2 = {
        "segments": [{"start_time": 1.0, "end_time": 2.0, "text": "Second chunk"}],
        "language": "en",
    }

    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe") as mock_whisper:
        mock_whisper.return_value = mock_result_1
        resp1 = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk1.wav", wav_bytes, "audio/wav")},
            data={"start_offset": 0.0, "sequence_number": 0},
        )
        assert resp1.status_code == 201

        mock_whisper.return_value = mock_result_2
        resp2 = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk2.wav", wav_bytes, "audio/wav")},
            data={"start_offset": 1.0, "sequence_number": 1},
        )
        assert resp2.status_code == 201

    # Verify meeting is still 'partial'
    status_resp = client.get(
        f"/api/v1/transcripts/meetings/{mtg_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["status"] == "partial"
    assert status_data["segment_count"] == 2


def test_meeting_end_finalizes_transcription(stage4_setup):
    """Calling host end_meeting transitions transcription_status from partial to completed."""
    mtg_id = stage4_setup["meeting_id"]
    part_id = stage4_setup["participant_id"]
    token = stage4_setup["token"]
    wav_bytes = _create_wav_bytes(1.0)

    # 1. Add a segment to make status 'partial'
    mock_result = {
        "segments": [{"start_time": 0.0, "end_time": 1.0, "text": "Speech before ending"}],
        "language": "en",
    }
    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", return_value=mock_result):
        resp = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk.wav", wav_bytes, "audio/wav")},
            data={"start_offset": 0.0, "sequence_number": 0},
        )
        assert resp.status_code == 201

    # Status is partial
    s1 = client.get(f"/api/v1/transcripts/meetings/{mtg_id}/status", headers={"Authorization": f"Bearer {token}"}).json()
    assert s1["status"] == "partial"

    # 2. Host ends the meeting
    end_resp = client.post(
        f"/api/v1/meetings/{mtg_id}/end",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert end_resp.status_code == 200
    assert end_resp.json()["status"] == "COMPLETED"

    # 3. Transcription status is now finalized to completed
    s2 = client.get(f"/api/v1/transcripts/meetings/{mtg_id}/status", headers={"Authorization": f"Bearer {token}"}).json()
    assert s2["status"] == "completed"
    assert s2["segment_count"] == 1


def test_audio_failure_preserves_existing_segments(stage4_setup):
    """Failure on a live chunk retains partial status and preserves existing transcript segments."""
    mtg_id = stage4_setup["meeting_id"]
    part_id = stage4_setup["participant_id"]
    token = stage4_setup["token"]
    wav_bytes = _create_wav_bytes(1.0)

    # 1. Successfully transcribe chunk 1
    mock_result = {
        "segments": [{"start_time": 0.0, "end_time": 1.0, "text": "Persisted valid segment"}],
        "language": "en",
    }
    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", return_value=mock_result):
        resp = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk1.wav", wav_bytes, "audio/wav")},
            data={"start_offset": 0.0, "sequence_number": 0},
        )
        assert resp.status_code == 201

    # 2. Chunk 2 triggers an error
    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", side_effect=RuntimeError("Whisper GPU OOM")):
        resp2 = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk2.wav", wav_bytes, "audio/wav")},
            data={"start_offset": 1.0, "sequence_number": 1},
        )
        assert resp2.status_code == 500

    # 3. Verify status remains partial (not wiped or masked) and segments exist
    status_resp = client.get(
        f"/api/v1/transcripts/meetings/{mtg_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["status"] == "partial"
    assert status_data["segment_count"] == 1
    assert "Whisper GPU OOM" in (status_data["error"] or "")

    # 4. Verify segment is still queryable
    transcript_resp = client.get(
        f"/api/v1/transcripts/meetings/{mtg_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert transcript_resp.status_code == 200
    t_data = transcript_resp.json()
    assert t_data["total_segments"] == 1
    assert t_data["segments"][0]["text"] == "Persisted valid segment"


def test_audio_failure_with_zero_segments_sets_failed(stage4_setup):
    """When chunk failure occurs with 0 prior segments, status is marked failed."""
    mtg_id = stage4_setup["meeting_id"]
    part_id = stage4_setup["participant_id"]
    token = stage4_setup["token"]
    wav_bytes = _create_wav_bytes(1.0)

    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", side_effect=RuntimeError("Engine Crash")):
        resp = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk1.wav", wav_bytes, "audio/wav")},
            data={"start_offset": 0.0, "sequence_number": 0},
        )
        assert resp.status_code == 500

    status_resp = client.get(
        f"/api/v1/transcripts/meetings/{mtg_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["status"] == "failed"
    assert status_data["segment_count"] == 0
    assert "Engine Crash" in (status_data["error"] or "")


def test_status_auto_resolves_when_meeting_completed(stage4_setup):
    """If meeting.status is COMPLETED and transcription_status is partial, status resolves to completed."""
    mtg_id = stage4_setup["meeting_id"]
    token = stage4_setup["token"]

    db = TestingSessionLocal()
    mtg = db.query(Meeting).filter(Meeting.public_id == mtg_id).first()
    mtg.status = MeetingStatus.COMPLETED.value
    mtg.transcription_status = "partial"
    db.commit()
    db.close()

    resp = client.get(
        f"/api/v1/transcripts/meetings/{mtg_id}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
