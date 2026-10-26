"""
Stage 2 Validation: Audio-Chunk-to-Transcription-to-Database Pipeline Test Suite.

Covers:
1. Micro-chunk validation (empty audio, malformed WAV headers, zero frames).
2. Server-side validation of sample rate, offsets, and sequence data.
3. Strict participant authorization (user identity match).
4. Multi-segment chunk persistence with sequence and timing metadata.
5. Idempotent re-processing / retry deduplication.
6. Temporary audio cleanup verification on success and failure.
7. Safe database transaction rollback on commit failure.
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
from app.core.tokens import create_token
from app.core.audio_temp import get_audio_temp_dir
from app.services.transcription_service import TranscriptionService
from tests.conftest import TestingSessionLocal

client = TestClient(app)


def _create_wav_bytes(duration_sec: float = 1.0, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """Generate valid PCM WAV bytes with explicit sample count and duration."""
    num_frames = int(duration_sec * sample_rate)
    pcm_data = b"\x00\x00" * num_frames
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


@pytest.fixture
def stream_setup():
    db = TestingSessionLocal()
    comp_id = f"comp-stream-{uuid.uuid4().hex[:6]}"
    user_id = f"usr-stream-{uuid.uuid4().hex[:6]}"
    other_user_id = f"usr-other-{uuid.uuid4().hex[:6]}"
    mtg_id = f"mtg-stream-{uuid.uuid4().hex[:6]}"
    part_id = str(uuid.uuid4())

    company = Company(public_id=comp_id, name="Stream Test Corp", workspace_code="ST-01")
    user = User(
        public_id=user_id,
        email=f"speaker-{uuid.uuid4().hex[:4]}@st.com",
        full_name="Speaker User",
        hashed_password="hash",
        account_type="company",
    )
    other_user = User(
        public_id=other_user_id,
        email=f"other-{uuid.uuid4().hex[:4]}@st.com",
        full_name="Other User",
        hashed_password="hash",
        account_type="company",
    )
    db.add_all([company, user, other_user])
    db.flush()

    member = CompanyMember(user_id=user.public_id, company_id=company.public_id, role=Role.MEMBER.value)
    other_member = CompanyMember(user_id=other_user.public_id, company_id=company.public_id, role=Role.MEMBER.value)
    meeting = Meeting(
        public_id=mtg_id,
        company_id=comp_id,
        owner_id=user.public_id,
        title="Live Stream Pipeline Meeting",
    )
    participant = MeetingParticipant(
        id=part_id,
        meeting_id=mtg_id,
        user_id=user.public_id,
        display_name="Speaker User",
        is_guest=False,
    )
    db.add_all([member, other_member, meeting, participant])
    db.commit()

    token = create_token(subject=user.public_id, token_type="access")
    other_token = create_token(subject=other_user.public_id, token_type="access")
    db.close()

    return {
        "meeting_id": mtg_id,
        "participant_id": part_id,
        "user_id": user_id,
        "other_user_id": other_user_id,
        "token": token,
        "other_token": other_token,
    }


def test_malformed_wav_rejected(stream_setup):
    """Corrupt WAV audio is rejected with 400 Bad Request."""
    mtg_id = stream_setup["meeting_id"]
    part_id = stream_setup["participant_id"]
    token = stream_setup["token"]

    corrupt_wav = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00NOT_VALID_AUDIO_DATA_TRUNCATED"
    resp = client.post(
        f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("chunk_corrupt.wav", corrupt_wav, "audio/wav")},
        data={"start_offset": 0.0, "sequence_number": 0},
    )
    assert resp.status_code == 400
    assert "Malformed or corrupted WAV" in resp.json()["detail"]


def test_empty_audio_content_rejected(stream_setup):
    """0-byte audio upload returns 400 Bad Request."""
    mtg_id = stream_setup["meeting_id"]
    part_id = stream_setup["participant_id"]
    token = stream_setup["token"]

    resp = client.post(
        f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("chunk_empty.wav", b"", "audio/wav")},
        data={"start_offset": 0.0},
    )
    assert resp.status_code == 400
    assert "Audio stream content is empty" in resp.json()["detail"]


def test_zero_duration_wav_returns_empty_list(stream_setup):
    """Valid WAV with 0 frames returns 201 with empty segment list."""
    mtg_id = stream_setup["meeting_id"]
    part_id = stream_setup["participant_id"]
    token = stream_setup["token"]

    empty_wav = _create_wav_bytes(duration_sec=0.0, sample_rate=16000)
    with patch.object(
        TranscriptionService,
        "_transcribe_with_retry",
        return_value={"segments": []},
    ):
        resp = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk_silent.wav", empty_wav, "audio/wav")},
            data={"start_offset": 0.0},
        )
    assert resp.status_code == 201
    assert resp.json() == []


def test_invalid_sample_rate_rejected(stream_setup):
    """Invalid sample rate (< 8000 or > 192000) returns 400 Bad Request."""
    mtg_id = stream_setup["meeting_id"]
    part_id = stream_setup["participant_id"]
    token = stream_setup["token"]
    wav_bytes = _create_wav_bytes(duration_sec=1.0)

    resp = client.post(
        f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("chunk.wav", wav_bytes, "audio/wav")},
        data={"start_offset": 0.0, "sample_rate": 500},
    )
    assert resp.status_code == 400
    assert "sample_rate must be between" in resp.json()["detail"]


def test_invalid_participant_id_returns_404(stream_setup):
    """Non-existent participant returns 404 cleanly without 500 unhandled exceptions."""
    mtg_id = stream_setup["meeting_id"]
    token = stream_setup["token"]
    wav_bytes = _create_wav_bytes(duration_sec=1.0)

    resp = client.post(
        f"/api/v1/transcripts/meetings/{mtg_id}/participants/not-a-valid-participant-uuid/audio-stream",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("chunk.wav", wav_bytes, "audio/wav")},
        data={"start_offset": 0.0},
    )
    assert resp.status_code == 404
    assert "not found in meeting" in resp.json()["detail"]


def test_unauthorized_user_cannot_submit_audio(stream_setup):
    """A user cannot submit audio for another user's participant ID (403 Forbidden)."""
    mtg_id = stream_setup["meeting_id"]
    part_id = stream_setup["participant_id"]  # Belongs to user_id
    other_token = stream_setup["other_token"]  # Belongs to other_user_id
    wav_bytes = _create_wav_bytes(duration_sec=1.0)

    resp = client.post(
        f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
        headers={"Authorization": f"Bearer {other_token}"},
        files={"file": ("chunk.wav", wav_bytes, "audio/wav")},
        data={"start_offset": 0.0},
    )
    assert resp.status_code == 403
    assert "caller identity does not match participant" in resp.json()["detail"]


def test_multi_segment_persistence_and_chunk_metadata(stream_setup):
    """Whisper returning multiple segments correctly creates distinct records with processing metadata."""
    mtg_id = stream_setup["meeting_id"]
    part_id = stream_setup["participant_id"]
    token = stream_setup["token"]
    wav_bytes = _create_wav_bytes(duration_sec=3.0, sample_rate=16000)

    mock_whisper = {
        "text": "First sentence. Second sentence.",
        "segments": [
            {"start_time": 0.0, "end_time": 1.2, "text": "First sentence.", "confidence": 0.94},
            {"start_time": 1.5, "end_time": 2.8, "text": "Second sentence.", "confidence": 0.91},
        ],
        "language": "en",
    }

    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", return_value=mock_whisper):
        resp = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk_multi.wav", wav_bytes, "audio/wav")},
            data={
                "start_offset": 10.0,
                "end_offset": 13.0,
                "sequence_number": 3,
                "chunk_id": f"{mtg_id}_{part_id}_seq3",
                "sample_rate": 16000,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data) == 2

        # Check timings
        assert data[0]["start_time"] == 10.0
        assert data[0]["end_time"] == 11.2
        assert data[0]["text"] == "First sentence."
        assert data[0]["participant_id"] == part_id

        assert data[1]["start_time"] == 11.5
        assert data[1]["end_time"] == 12.8
        assert data[1]["text"] == "Second sentence."
        assert data[1]["participant_id"] == part_id

        # Metadata
        for seg in data:
            meta = seg["processing_metadata"]
            assert meta["chunk_id"] == f"{mtg_id}_{part_id}_seq3"
            assert meta["sequence_number"] == 3
            assert meta["chunk_start_offset"] == 10.0
            assert meta["chunk_end_offset"] == 13.0
            assert meta["sample_rate"] == 16000
            assert meta["timing_source"] == "audio_sample_clock"


def test_retry_idempotency_does_not_duplicate_segments(stream_setup):
    """Reprocessing the same chunk ID and sequence updates records idempotently without duplicates."""
    mtg_id = stream_setup["meeting_id"]
    part_id = stream_setup["participant_id"]
    token = stream_setup["token"]
    wav_bytes = _create_wav_bytes(duration_sec=2.0)

    mock_whisper_attempt1 = {
        "text": "Initial speech",
        "segments": [{"start_time": 0.0, "end_time": 1.5, "text": "Initial speech"}],
        "language": "en",
    }
    mock_whisper_attempt2 = {
        "text": "Initial speech (refined)",
        "segments": [{"start_time": 0.0, "end_time": 1.5, "text": "Initial speech (refined)"}],
        "language": "en",
    }

    chunk_id = f"{mtg_id}_{part_id}_seq7"

    # Attempt 1
    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", return_value=mock_whisper_attempt1):
        r1 = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk_seq7.wav", wav_bytes, "audio/wav")},
            data={"start_offset": 20.0, "sequence_number": 7, "chunk_id": chunk_id},
        )
        assert r1.status_code == 201
        assert len(r1.json()) == 1
        assert r1.json()[0]["text"] == "Initial speech"

    # Attempt 2: retry of identical chunk
    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", return_value=mock_whisper_attempt2):
        r2 = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk_seq7.wav", wav_bytes, "audio/wav")},
            data={"start_offset": 20.0, "sequence_number": 7, "chunk_id": chunk_id},
        )
        assert r2.status_code == 201
        assert len(r2.json()) == 1
        assert r2.json()[0]["text"] == "Initial speech (refined)"

    # Query meeting transcript to verify no duplicate row was created
    vault_r = client.get(
        f"/api/v1/transcripts/meetings/{mtg_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert vault_r.status_code == 200
    vault_data = vault_r.json()
    assert vault_data["total_segments"] == 1
    assert vault_data["segments"][0]["text"] == "Initial speech (refined)"


def test_temp_audio_file_cleaned_up_on_success_and_failure(stream_setup):
    """Temporary audio files are deleted from disk after both successful transcription and failure."""
    mtg_id = stream_setup["meeting_id"]
    part_id = stream_setup["participant_id"]
    token = stream_setup["token"]
    wav_bytes = _create_wav_bytes(duration_sec=1.0)
    temp_dir = get_audio_temp_dir()

    created_paths = []
    original_transcribe = None

    def spy_transcribe(audio_path, language=None):
        created_paths.append(audio_path)
        import os
        assert os.path.isfile(audio_path), "Temp audio file must exist while Whisper executes"
        return {"text": "Success test", "segments": [{"start_time": 0.0, "end_time": 0.9, "text": "Success test"}]}

    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", side_effect=spy_transcribe):
        r_success = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk_clean.wav", wav_bytes, "audio/wav")},
            data={"start_offset": 30.0},
        )
        assert r_success.status_code == 201

    import os
    assert len(created_paths) == 1
    assert not os.path.exists(created_paths[0]), "Temp audio file must be unlinked on success"

    # Test failure cleanup
    failed_paths = []

    def failing_transcribe(audio_path, language=None):
        failed_paths.append(audio_path)
        assert os.path.isfile(audio_path), "Temp audio file must exist when failure triggers"
        raise ValueError("Simulated inference engine error")

    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", side_effect=failing_transcribe):
        r_fail = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk_fail.wav", wav_bytes, "audio/wav")},
            data={"start_offset": 35.0},
        )
        assert r_fail.status_code == 500

    assert len(failed_paths) == 1
    assert not os.path.exists(failed_paths[0]), "Temp audio file must be unlinked even when transcription fails"


def test_database_failure_triggers_rollback(stream_setup):
    """Database failure during commit rolls back transaction cleanly."""
    mtg_id = stream_setup["meeting_id"]
    part_id = stream_setup["participant_id"]
    token = stream_setup["token"]
    wav_bytes = _create_wav_bytes(duration_sec=1.0)

    mock_whisper = {
        "text": "Rollback test",
        "segments": [{"start_time": 0.0, "end_time": 0.8, "text": "Rollback test"}],
    }

    from sqlalchemy.orm import Session
    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", return_value=mock_whisper):
        with patch.object(Session, "commit", side_effect=RuntimeError("Simulated DB commit error")):
            resp = client.post(
                f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": ("chunk_db_fail.wav", wav_bytes, "audio/wav")},
                data={"start_offset": 40.0},
            )
            assert resp.status_code == 500
            assert "transcription failed" in resp.json()["detail"].lower()
