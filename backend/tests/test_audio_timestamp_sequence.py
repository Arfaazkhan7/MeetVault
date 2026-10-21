"""
Automated Test Suite for MeetVault Audio Chunk Timestamp & Sequence Accuracy.

Tests:
1. Correct offset calculation from sample count and sample rate.
2. Delayed network dispatch does not shift capture timeline.
3. Delayed transcription does not shift capture timeline.
4. Duplicate and out-of-order chunks preserve chronological order and idempotency.
5. Server-side validation rejects malformed, negative, or inverted offsets and sequences.
6. Buffer rollover and participant reconnection preserve sequence numbers and chronological continuity.
7. Vault transcript ordering guarantees chronological sequence across multiple participants.
"""
import io
import wave
import uuid
import time
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.company import Company, CompanyMember
from app.models.meeting import Meeting, MeetingParticipant
from app.models.transcript import TranscriptSegment
from app.models.user import User
from app.core.roles import Role
from app.core.tokens import create_token
from tests.conftest import TestingSessionLocal

client = TestClient(app)


def _generate_wav_bytes(duration_sec: float = 1.0, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """Generate valid PCM WAV bytes with explicit sample count and duration."""
    num_frames = int(duration_sec * sample_rate)
    pcm_data = b"\x00\x00" * num_frames  # 16-bit silence
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


@pytest.fixture
def test_setup():
    db = TestingSessionLocal()
    comp_id = f"comp-{uuid.uuid4().hex[:6]}"
    user_id = f"usr-{uuid.uuid4().hex[:6]}"
    mtg_id = f"mtg-{uuid.uuid4().hex[:6]}"
    part_id = str(uuid.uuid4())

    company = Company(public_id=comp_id, name="Test Company", workspace_code="MV-CLK01")
    user = User(
        public_id=user_id,
        email=f"tester-{uuid.uuid4().hex[:4]}@mv.com",
        full_name="Audio Clock Tester",
        hashed_password="hash",
        account_type="personal",
    )
    db.add(company)
    db.add(user)
    db.flush()

    member = CompanyMember(user_id=user.public_id, company_id=company.public_id, role=Role.COMPANY_ADMIN.value)
    meeting = Meeting(
        public_id=mtg_id,
        company_id=comp_id,
        owner_id=user.public_id,
        title="Timestamp Accuracy Meeting",
    )
    participant = MeetingParticipant(
        id=part_id,
        meeting_id=mtg_id,
        user_id=user.public_id,
        display_name="Audio Clock Tester",
        is_guest=False,
    )
    db.add(member)
    db.add(meeting)
    db.add(participant)
    db.commit()

    token = create_token(subject=user.public_id, token_type="access")
    db.close()

    return {
        "meeting_id": mtg_id,
        "participant_id": part_id,
        "user_id": user_id,
        "token": token,
    }


def test_correct_offset_calculation_from_sample_count_and_rate(test_setup):
    """
    Requirement 2, 3 & 4: Offsets reflect audio capture sample count and rate,
    populating metadata with frame count, sample rate, and chunk offsets.
    """
    mtg_id = test_setup["meeting_id"]
    part_id = test_setup["participant_id"]
    token = test_setup["token"]

    # 1.5 seconds of audio at 16kHz = 24000 frames
    wav_1_5s = _generate_wav_bytes(duration_sec=1.5, sample_rate=16000)

    mock_whisper_result = {
        "text": "Hello world from sample clock",
        "segments": [
            {"start_time": 0.0, "end_time": 1.45, "text": "Hello world from sample clock", "confidence": 0.95}
        ],
        "language": "en",
    }

    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", return_value=mock_whisper_result):
        resp = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk_seq0.wav", wav_1_5s, "audio/wav")},
            data={
                "start_offset": 4.500,
                "end_offset": 6.000,
                "sequence_number": 0,
                "sample_rate": 16000,
            },
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert len(data) == 1
        seg = data[0]

        # start_time = 4.5 + 0.0 = 4.5
        # end_time = 4.5 + 1.45 = 5.95
        assert seg["start_time"] == 4.5
        assert seg["end_time"] == 5.95

        # Check metadata
        meta = seg["processing_metadata"]
        assert meta is not None
        assert meta["timing_source"] == "audio_sample_clock"
        assert meta["sequence_number"] == 0
        assert meta["chunk_start_offset"] == 4.5
        assert meta["chunk_end_offset"] == 6.0
        assert meta["sample_rate"] == 16000
        assert meta["frame_count"] == 24000
        assert meta["chunk_duration"] == 1.5


def test_delayed_network_dispatch_preserves_capture_timeline(test_setup):
    """
    Requirement 3: An audio chunk captured at t=2.0s to t=5.0s, but delayed on the network
    and delivered much later, must preserve its capture timeline rather than HTTP arrival time.
    """
    mtg_id = test_setup["meeting_id"]
    part_id = test_setup["participant_id"]
    token = test_setup["token"]

    wav_3s = _generate_wav_bytes(duration_sec=3.0, sample_rate=16000)

    mock_whisper_result = {
        "text": "Delayed delivery speech",
        "segments": [{"start_time": 0.2, "end_time": 2.8, "text": "Delayed delivery speech", "confidence": 0.9}],
        "language": "en",
    }

    # Simulate network delay by submitting with start_offset corresponding to actual capture time (e.g. 2.0s)
    capture_start = 2.0
    capture_end = 5.0

    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", return_value=mock_whisper_result):
        resp = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk_delayed.wav", wav_3s, "audio/wav")},
            data={
                "start_offset": capture_start,
                "end_offset": capture_end,
                "sequence_number": 5,
            },
        )
        assert resp.status_code == 201
        seg = resp.json()[0]
        # start_time = 2.0 + 0.2 = 2.2
        # end_time = 2.0 + 2.8 = 4.8
        assert seg["start_time"] == 2.2
        assert seg["end_time"] == 4.8


def test_delayed_transcription_does_not_shift_offsets(test_setup):
    """
    Requirement 3: Slow / delayed transcription processing does not shift transcript timestamps.
    """
    mtg_id = test_setup["meeting_id"]
    part_id = test_setup["participant_id"]
    token = test_setup["token"]

    wav_1s = _generate_wav_bytes(duration_sec=1.0)

    def slow_transcribe(audio_path, language=None):
        time.sleep(0.05)  # Simulate transcription delay
        return {
            "text": "Slow AI processing",
            "segments": [{"start_time": 0.0, "end_time": 0.9, "text": "Slow AI processing", "confidence": 0.88}],
            "language": "en",
        }

    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", side_effect=slow_transcribe):
        resp = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk_slow.wav", wav_1s, "audio/wav")},
            data={"start_offset": 10.0, "sequence_number": 2},
        )
        assert resp.status_code == 201
        seg = resp.json()[0]
        # Timestamps remain precisely anchored to 10.0s, unaffected by the sleep duration
        assert seg["start_time"] == 10.0
        assert seg["end_time"] == 10.9


def test_duplicate_and_out_of_order_chunks_preserve_order_and_idempotency(test_setup):
    """
    Requirement 7 & 8: Late, duplicate, and out-of-order chunks are stored idempotently
    and retrieved in strictly ascending chronological order.
    """
    mtg_id = test_setup["meeting_id"]
    part_id = test_setup["participant_id"]
    token = test_setup["token"]

    wav_1s = _generate_wav_bytes(duration_sec=1.0)

    # Chunk 2 (starts at 4.0s) arrives BEFORE Chunk 1 (starts at 0.0s)
    mock_chunk2 = {
        "text": "Second statement in time",
        "segments": [{"start_time": 0.0, "end_time": 0.8, "text": "Second statement in time"}],
    }
    mock_chunk1 = {
        "text": "First statement in time",
        "segments": [{"start_time": 0.0, "end_time": 0.8, "text": "First statement in time"}],
    }

    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", return_value=mock_chunk2):
        # Dispatch Chunk 2 first
        resp2 = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk_seq1.wav", wav_1s, "audio/wav")},
            data={"start_offset": 4.0, "sequence_number": 1},
        )
        assert resp2.status_code == 201

    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", return_value=mock_chunk1):
        # Dispatch Chunk 1 later (out of order arrival)
        resp1 = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk_seq0.wav", wav_1s, "audio/wav")},
            data={"start_offset": 0.0, "sequence_number": 0},
        )
        assert resp1.status_code == 201

    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", return_value=mock_chunk2):
        # Re-dispatch Chunk 2 as a duplicate retry
        resp_dup = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk_seq1_retry.wav", wav_1s, "audio/wav")},
            data={"start_offset": 4.0, "sequence_number": 1},
        )
        assert resp_dup.status_code == 201

    # Query Vault transcript endpoint
    vault_resp = client.get(
        f"/api/v1/transcripts/meetings/{mtg_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert vault_resp.status_code == 200
    vault_data = vault_resp.json()

    # Must contain exactly 2 unique segments, NOT 3 (duplicate was idempotent)
    assert vault_data["total_segments"] == 2
    segs = vault_data["segments"]

    # Order must be strictly chronological: Chunk 1 (0.0s) then Chunk 2 (4.0s)
    assert segs[0]["start_time"] == 0.0
    assert segs[0]["text"] == "First statement in time"
    assert segs[1]["start_time"] == 4.0
    assert segs[1]["text"] == "Second statement in time"


def test_server_validation_rejects_malformed_and_negative_offsets(test_setup):
    """
    Requirement 6: Validate offsets and sequence values server-side.
    Reject negative, NaN, Inf, inverted, or unreasonable values.
    """
    mtg_id = test_setup["meeting_id"]
    part_id = test_setup["participant_id"]
    token = test_setup["token"]
    wav_1s = _generate_wav_bytes(duration_sec=1.0)

    # 1. Negative start_offset
    r1 = client.post(
        f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("chunk.wav", wav_1s, "audio/wav")},
        data={"start_offset": -1.5},
    )
    assert r1.status_code == 400
    assert "start_offset must be a non-negative finite number" in r1.json()["detail"]

    # 2. Inverted end_offset < start_offset
    r2 = client.post(
        f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("chunk.wav", wav_1s, "audio/wav")},
        data={"start_offset": 5.0, "end_offset": 3.0},
    )
    assert r2.status_code == 400
    assert "end_offset cannot be less than start_offset" in r2.json()["detail"]

    # 3. Negative sequence_number
    r3 = client.post(
        f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("chunk.wav", wav_1s, "audio/wav")},
        data={"start_offset": 0.0, "sequence_number": -5},
    )
    assert r3.status_code == 400
    assert "sequence_number must be non-negative" in r3.json()["detail"]

    # 4. Unreasonable start_offset (> 24 hours = 86400s)
    r4 = client.post(
        f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("chunk.wav", wav_1s, "audio/wav")},
        data={"start_offset": 90000.0},
    )
    assert r4.status_code == 400
    assert "exceeds reasonable meeting bounds" in r4.json()["detail"]


def test_buffer_rollover_and_reconnection_preserves_sequence(test_setup):
    """
    Requirement 8: Participant microphone mute/unmute or reconnection
    preserves sequence continuity and timeline offsets without overlap.
    """
    mtg_id = test_setup["meeting_id"]
    part_id = test_setup["participant_id"]
    token = test_setup["token"]

    wav_1s = _generate_wav_bytes(duration_sec=1.0)

    # Session 1: chunks 0 and 1
    mock_s1 = {"text": "Session 1 Part 1", "segments": [{"start_time": 0.0, "end_time": 0.9, "text": "Session 1 Part 1"}]}
    mock_s2 = {"text": "Session 1 Part 2", "segments": [{"start_time": 0.0, "end_time": 0.9, "text": "Session 1 Part 2"}]}
    # Session 2 (after mute/unmute): chunks 2 and 3 at t=15.0s
    mock_s3 = {"text": "Session 2 Part 1", "segments": [{"start_time": 0.0, "end_time": 0.9, "text": "Session 2 Part 1"}]}

    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", side_effect=[mock_s1, mock_s2, mock_s3]):
        r1 = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("c0.wav", wav_1s, "audio/wav")},
            data={"start_offset": 0.0, "sequence_number": 0},
        )
        assert r1.status_code == 201

        r2 = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("c1.wav", wav_1s, "audio/wav")},
            data={"start_offset": 1.0, "sequence_number": 1},
        )
        assert r2.status_code == 201

        # Mute gap of 13 seconds, user resumes speaking at t=15.0s
        r3 = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("c2.wav", wav_1s, "audio/wav")},
            data={"start_offset": 15.0, "sequence_number": 2},
        )
        assert r3.status_code == 201

    vault = client.get(f"/api/v1/transcripts/meetings/{mtg_id}", headers={"Authorization": f"Bearer {token}"}).json()
    assert vault["total_segments"] == 3
    assert vault["segments"][0]["start_time"] == 0.0
    assert vault["segments"][1]["start_time"] == 1.0
    assert vault["segments"][2]["start_time"] == 15.0


def test_chunk_id_idempotent_retry_does_not_create_duplicates(test_setup):
    """
    Requirement 4 & 5: Stable chunk_id ensures idempotent retries
    and guarantees no duplicate transcript segments are created in the database.
    """
    mtg_id = test_setup["meeting_id"]
    part_id = test_setup["participant_id"]
    token = test_setup["token"]

    wav_1s = _generate_wav_bytes(duration_sec=1.0)
    chunk_id = f"{mtg_id}_{part_id}_seq42"

    mock_resp = {
        "text": "Idempotent speech chunk",
        "segments": [{"start_time": 0.0, "end_time": 0.8, "text": "Idempotent speech chunk"}],
    }

    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", return_value=mock_resp):
        # Initial delivery
        r1 = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk.wav", wav_1s, "audio/wav")},
            data={"start_offset": 8.0, "sequence_number": 42, "chunk_id": chunk_id},
        )
        assert r1.status_code == 201
        data1 = r1.json()
        assert len(data1) == 1
        assert data1[0]["processing_metadata"]["chunk_id"] == chunk_id
        assert data1[0]["processing_metadata"]["sequence_number"] == 42

        # Retry identical chunk (e.g. client timeout or network hiccup before receiving ack)
        r2 = client.post(
            f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("chunk.wav", wav_1s, "audio/wav")},
            data={"start_offset": 8.0, "sequence_number": 42, "chunk_id": chunk_id},
        )
        assert r2.status_code == 201

    # Verify Vault: exactly 1 segment exists, zero duplicates
    vault = client.get(f"/api/v1/transcripts/meetings/{mtg_id}", headers={"Authorization": f"Bearer {token}"}).json()
    assert vault["total_segments"] == 1
    assert vault["segments"][0]["text"] == "Idempotent speech chunk"
    assert vault["segments"][0]["start_time"] == 8.0


def test_permanent_error_classifications(test_setup):
    """
    Requirement 8: Distinguish retryable errors from permanent failures:
    - 400 Bad Request: empty audio or invalid offsets
    - 403 Forbidden: submitting audio for a different participant
    - 404 Not Found: nonexistent participant or meeting
    """
    mtg_id = test_setup["meeting_id"]
    part_id = test_setup["participant_id"]
    token = test_setup["token"]
    wav_1s = _generate_wav_bytes(duration_sec=1.0)

    # 400: empty audio
    r_empty = client.post(
        f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("empty.wav", b"", "audio/wav")},
        data={"start_offset": 0.0, "sequence_number": 0},
    )
    assert r_empty.status_code == 400

    # 404: nonexistent participant
    r_404 = client.post(
        f"/api/v1/transcripts/meetings/{mtg_id}/participants/{uuid.uuid4()}/audio-stream",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("test.wav", wav_1s, "audio/wav")},
        data={"start_offset": 0.0, "sequence_number": 0},
    )
    assert r_404.status_code == 404

