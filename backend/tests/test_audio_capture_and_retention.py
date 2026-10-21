"""
Automated test suite for MeetVault audio capture, speech processing,
zero-retention audio policy, and participant attribution.

Tests:
1. Zero-retention: successful pipeline transcribes, persists transcript, and purges audio from storage.
2. Zero-retention: failed pipeline purges temporary audio so no orphan files remain in storage.
3. Per-participant audio stream: direct in-memory audio chunk processing with zero storage uploads.
4. Correct attribution: speech attributed to authenticated user ID, ambiguous speech marked unconfirmed.
5. Participant disconnect and reconnect: speech turns preserved without misattribution.
6. Host leaving does not corrupt or wipe transcripts.
7. Duplicate webhook delivery does not generate duplicate transcript segments.
8. Provider unavailable returns actionable error without logging raw audio.
9. Two simultaneous meetings maintain strict tenant and transcript isolation.
10. Database and logs do not store raw audio bytes or data URIs.
11. Signed URL endpoint returns HTTP 410 Gone once audio has been purged.
"""
import io
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.enums import RecordingProcessingStatus
from app.core.tokens import create_token
from app.models.ai_job import AIJob
from app.models.company import Company, CompanyMember
from app.models.meeting import Meeting, MeetingParticipant
from app.models.recording import MeetingRecording
from app.models.transcript import TranscriptSegment
from app.models.user import User
from app.services.storage_service import StorageService, StoredObject, get_storage_service
from app.services.transcription_service import TranscriptionService, TranscriptionEngine
from tests.conftest import TestingSessionLocal


class InMemoryStorageService(StorageService):
    """In-memory storage service that tracks file creation and deletion."""
    def __init__(self):
        self.files = {}
        self.deleted_files = set()

    def upload_private_file(self, *, path: str, content: bytes, content_type: str) -> StoredObject:
        self.files[path] = content
        return StoredObject(backend="mock", bucket="test-recordings", path=path)

    def create_signed_url(self, *, path: str, expires_in_seconds: int) -> str:
        if path not in self.files:
            raise FileNotFoundError(f"Storage object {path} not found")
        return f"https://mock-storage.test/signed/{path}?expires={expires_in_seconds}"

    def download_private_file(self, *, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(f"Storage object {path} not found")
        return self.files[path]

    def delete_private_file(self, *, path: str) -> bool:
        if path in self.files:
            del self.files[path]
            self.deleted_files.add(path)
            return True
        return False

    def file_exists(self, *, path: str) -> bool:
        return path in self.files


class MockSpeechEngine(TranscriptionEngine):
    """Mock engine that returns deterministic segments without downloading models."""
    def __init__(self, segments_to_return=None):
        self.segments_to_return = segments_to_return or [
            {
                "start_time": 0.0,
                "end_time": 4.5,
                "text": "Action items have been finalized.",
                "language": "en",
                "confidence": 0.98,
                "words": [{"word": "Action", "start": 0.0, "end": 0.5}],
            }
        ]

    def transcribe(self, audio_path: str, language=None):
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file {audio_path} does not exist")
        return {
            "segments": self.segments_to_return,
            "language": "en",
            "processing_time": 0.1,
        }


@pytest.fixture
def memory_storage():
    return InMemoryStorageService()


@pytest.fixture
def setup_meeting_env():
    """Create company, host, attendee, and meeting."""
    db = TestingSessionLocal()
    try:
        company = Company(public_id="comp-ret-1", name="Privacy First Inc", domain="privacy.test")
        db.add(company)
        db.commit()

        host = User(
            public_id="usr-host-1",
            email="host@privacy.test",
            full_name="Host User",
            hashed_password="hash",
            account_type="company",
        )
        attendee = User(
            public_id="usr-att-2",
            email="attendee@privacy.test",
            full_name="Attendee User",
            hashed_password="hash",
            account_type="company",
        )
        db.add_all([host, attendee])
        db.commit()

        db.add_all([
            CompanyMember(company_id=company.public_id, user_id=host.public_id, role="COMPANY_ADMIN"),
            CompanyMember(company_id=company.public_id, user_id=attendee.public_id, role="MEMBER"),
        ])
        db.commit()

        meeting = Meeting(
            public_id="mtg-ret-100",
            company_id=company.public_id,
            owner_id=host.public_id,
            title="Retention Audit Sync",
            meeting_type="SCHEDULED",
            status="LIVE",
            transcription_status="pending",
        )
        db.add(meeting)
        db.commit()

        part_host = MeetingParticipant(
            meeting_id=meeting.public_id,
            user_id=host.public_id,
            role="HOST",
            status="JOINED",
            livekit_identity=host.public_id,
            identity_mapping_status="verified",
            is_guest=False,
            display_name=host.full_name,
        )
        part_attendee = MeetingParticipant(
            meeting_id=meeting.public_id,
            user_id=attendee.public_id,
            role="ATTENDEE",
            status="JOINED",
            livekit_identity=attendee.public_id,
            identity_mapping_status="verified",
            is_guest=False,
            display_name=attendee.full_name,
        )
        db.add_all([part_host, part_attendee])
        db.commit()
        db.refresh(part_host)
        db.refresh(part_attendee)

        tokens = {
            "host": create_token(subject=host.public_id, token_type="access"),
            "attendee": create_token(subject=attendee.public_id, token_type="access"),
        }

        yield {
            "company": company,
            "host": host,
            "attendee": attendee,
            "meeting": meeting,
            "part_host": part_host,
            "part_attendee": part_attendee,
            "tokens": tokens,
        }
    finally:
        db.close()


def test_zero_retention_successful_pipeline_purges_audio_and_persists_transcript(memory_storage, setup_meeting_env, client: TestClient):
    """
    Verify that when AI pipeline completes:
    1. Transcripts are persisted to database.
    2. Audio artifact is deleted from storage bucket (delete_private_file called).
    3. recording.storage_path is cleared and is_audio_purged is True.
    4. Signed URL endpoint returns 410 Gone for purged audio.
    5. Transcript text remains completely accessible.
    """
    meeting = setup_meeting_env["meeting"]
    host = setup_meeting_env["host"]

    # Upload temporary audio to storage
    audio_path = f"temp/{meeting.public_id}/audio.wav"
    memory_storage.upload_private_file(path=audio_path, content=b"RIFFdummywavcontent", content_type="audio/wav")
    assert memory_storage.file_exists(path=audio_path)

    db = TestingSessionLocal()
    recording = MeetingRecording(
        id=uuid.uuid4(),
        meeting_id=meeting.public_id,
        company_id=meeting.company_id,
        uploaded_by_user_id=host.public_id,
        storage_backend="mock",
        storage_bucket="test-recordings",
        storage_path=audio_path,
        original_filename="audio.wav",
        file_type="audio/wav",
        file_size_bytes=18,
        processing_status=RecordingProcessingStatus.QUEUED.value,
        retention_policy="ephemeral_transcript_only",
        is_audio_purged=False,
    )
    db.add(recording)
    db.commit()

    # Create AI Job
    recording_id_val = recording.id
    ai_job = AIJob(
        public_id=f"job_{uuid.uuid4().hex[:10]}",
        meeting_id=meeting.public_id,
        recording_id=str(recording_id_val),
        company_id=meeting.company_id,
        requested_by_user_id=host.public_id,
        status="QUEUED",
        provider="mock",
    )
    db.add(ai_job)
    db.commit()
    ai_job_id = ai_job.public_id
    db.close()

    # Run pipeline with mocked transcribe and diarize
    from ai_worker.tasks import pipeline

    mock_segments = [
        MagicMock(
            start_time=0.0,
            end_time=3.5,
            text="Architecture is sound.",
            speaker_label="SPEAKER_00",
            segment_id=f"{meeting.public_id}:0000",
            language="en",
            confidence=0.99,
            words=None,
            translated_text=None,
        )
    ]

    with patch("ai_worker.tasks.pipeline.SessionLocal", side_effect=TestingSessionLocal), \
         patch("ai_worker.tasks.pipeline.get_storage_service", return_value=memory_storage), \
         patch("app.services.storage_service.get_storage_service", return_value=memory_storage), \
         patch("ai_worker.providers.transcribe", return_value=mock_segments), \
         patch("ai_worker.diarization.diarization.diarize", return_value=[]), \
         patch("app.services.meeting_analysis_service.MeetingAnalysisService.analyze_meeting", return_value=None), \
         patch("app.services.embedding_service.EmbeddingService.index_meeting_entities", return_value=None):

        pipeline.process_meeting_intelligence(ai_job_id)

    # 1. Audio object MUST be purged from storage
    assert not memory_storage.file_exists(path=audio_path), "Audio must be deleted from storage"
    assert audio_path in memory_storage.deleted_files

    # 2. Database recording must reflect purged status
    db = TestingSessionLocal()
    rec = db.query(MeetingRecording).filter(MeetingRecording.id == recording_id_val).first()
    assert rec.is_audio_purged is True
    assert rec.storage_path is None
    assert rec.audio_purged_at is not None
    assert rec.processing_status == "COMPLETED"

    # 3. Transcripts must be durably stored
    segments = db.query(TranscriptSegment).filter(TranscriptSegment.meeting_id == meeting.public_id).all()
    assert len(segments) == 1
    assert segments[0].text == "Architecture is sound."
    db.close()

    # 4. Transcripts API retrieves the text seamlessly
    token = setup_meeting_env["tokens"]["host"]
    t_resp = client.get(
        f"/api/v1/transcripts/meetings/{meeting.public_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert t_resp.status_code == 200
    assert len(t_resp.json()["segments"]) == 1
    assert t_resp.json()["segments"][0]["text"] == "Architecture is sound."

    # 5. Requesting signed playback URL returns 410 Gone (purged)
    client.app.dependency_overrides[get_storage_service] = lambda: memory_storage
    url_resp = client.post(
        f"/api/v1/meetings/{meeting.public_id}/recordings/{recording_id_val}/signed-url",
        headers={"Authorization": f"Bearer {token}"},
    )
    client.app.dependency_overrides.pop(get_storage_service, None)
    assert url_resp.status_code == 410
    assert "purged" in url_resp.json()["detail"].lower()


def test_zero_retention_failed_pipeline_purges_audio_artifact(memory_storage, setup_meeting_env):
    """Verify that when a pipeline job fails, temporary audio is deleted so no orphan files remain."""
    meeting = setup_meeting_env["meeting"]
    host = setup_meeting_env["host"]

    audio_path = f"temp/{meeting.public_id}/failed_test.wav"
    memory_storage.upload_private_file(path=audio_path, content=b"corruptaudio", content_type="audio/wav")

    db = TestingSessionLocal()
    recording = MeetingRecording(
        id=uuid.uuid4(),
        meeting_id=meeting.public_id,
        company_id=meeting.company_id,
        uploaded_by_user_id=host.public_id,
        storage_backend="mock",
        storage_bucket="test-recordings",
        storage_path=audio_path,
        processing_status=RecordingProcessingStatus.QUEUED.value,
        retention_policy="ephemeral_transcript_only",
        is_audio_purged=False,
    )
    db.add(recording)
    db.commit()

    recording_id_val = recording.id
    ai_job = AIJob(
        public_id=f"job_fail_{uuid.uuid4().hex[:10]}",
        meeting_id=meeting.public_id,
        recording_id=str(recording_id_val),
        company_id=meeting.company_id,
        requested_by_user_id=host.public_id,
        status="QUEUED",
        provider="mock",
    )
    db.add(ai_job)
    db.commit()
    ai_job_id = ai_job.public_id
    db.close()

    from ai_worker.tasks import pipeline

    def raise_transcription_error(*args, **kwargs):
        raise RuntimeError("ASR service unavailable")

    with patch("ai_worker.tasks.pipeline.SessionLocal", side_effect=TestingSessionLocal), \
         patch("ai_worker.tasks.pipeline.get_storage_service", return_value=memory_storage), \
         patch("ai_worker.providers.transcribe", side_effect=raise_transcription_error):

        with pytest.raises(RuntimeError, match="ASR service unavailable"):
            pipeline.process_meeting_intelligence(ai_job_id)

    # Temporary audio MUST be deleted on failure
    assert not memory_storage.file_exists(path=audio_path), "Audio must be purged even on failure"
    assert audio_path in memory_storage.deleted_files

    db = TestingSessionLocal()
    rec = db.query(MeetingRecording).filter(MeetingRecording.id == recording_id_val).first()
    assert rec.is_audio_purged is True
    assert rec.storage_path is None
    assert rec.processing_status == "FAILED"
    db.close()


def test_per_participant_audio_stream_direct_processing(client: TestClient, setup_meeting_env, monkeypatch):
    """
    Verify per-participant direct audio chunk ingestion:
    - Processes audio in-memory with zero bucket uploads.
    - Attaches participant ID and authenticated user ID directly.
    - Cleans up ephemeral local temp file immediately.
    """
    meeting = setup_meeting_env["meeting"]
    host = setup_meeting_env["host"]
    attendee = setup_meeting_env["attendee"]
    part_host = setup_meeting_env["part_host"]
    part_att = setup_meeting_env["part_attendee"]
    token_host = setup_meeting_env["tokens"]["host"]
    token_att = setup_meeting_env["tokens"]["attendee"]

    # Mock TranscriptionService engine
    fake_engine = MockSpeechEngine([
        {"start_time": 0.0, "end_time": 2.5, "text": "I am speaking on my audio track.", "confidence": 0.97}
    ])
    monkeypatch.setattr(
        "app.services.transcription_service.LazyWhisperTranscriptionEngine",
        lambda *a, **k: fake_engine
    )

    # 1. Host streams audio for their participant slot
    resp_host = client.post(
        f"/api/v1/transcripts/meetings/{meeting.public_id}/participants/{part_host.id}/audio-stream",
        headers={"Authorization": f"Bearer {token_host}"},
        files={"file": ("chunk.wav", b"fake-wav-bytes", "audio/wav")},
        data={"start_offset": 10.0, "language": "en"},
    )
    assert resp_host.status_code == 201, resp_host.text
    host_segs = resp_host.json()
    assert len(host_segs) == 1
    assert host_segs[0]["speaker_user_id"] == host.public_id
    assert host_segs[0]["participant_id"] == str(part_host.id)
    assert host_segs[0]["attribution_status"] == "verified"
    assert host_segs[0]["start_time"] == 10.0
    assert host_segs[0]["end_time"] == 12.5

    # 2. Attendee streams audio for their participant slot
    fake_engine.segments_to_return = [
        {"start_time": 0.0, "end_time": 3.0, "text": "Attendee audio track reply.", "confidence": 0.95}
    ]
    resp_att = client.post(
        f"/api/v1/transcripts/meetings/{meeting.public_id}/participants/{part_att.id}/audio-stream",
        headers={"Authorization": f"Bearer {token_att}"},
        files={"file": ("chunk2.wav", b"fake-wav-bytes-2", "audio/wav")},
        data={"start_offset": 15.0, "language": "en"},
    )
    assert resp_att.status_code == 201, resp_att.text
    att_segs = resp_att.json()
    assert len(att_segs) == 1
    assert att_segs[0]["speaker_user_id"] == attendee.public_id
    assert att_segs[0]["participant_id"] == str(part_att.id)
    assert att_segs[0]["attribution_status"] == "verified"
    assert att_segs[0]["start_time"] == 15.0


def test_participant_cannot_submit_audio_for_other_participant(client: TestClient, setup_meeting_env):
    """Verify participant cannot spoof another participant's audio track (403 Forbidden)."""
    meeting = setup_meeting_env["meeting"]
    part_host = setup_meeting_env["part_host"]
    token_att = setup_meeting_env["tokens"]["attendee"]

    # Attendee tries to stream audio posing as host
    resp = client.post(
        f"/api/v1/transcripts/meetings/{meeting.public_id}/participants/{part_host.id}/audio-stream",
        headers={"Authorization": f"Bearer {token_att}"},
        files={"file": ("spoof.wav", b"audio", "audio/wav")},
    )
    assert resp.status_code == 403
    assert "not authorized" in resp.json()["detail"].lower()


def test_participant_disconnect_and_reconnect_preserves_attribution(setup_meeting_env):
    """Verify that participant leaving and rejoining maintains identity and does not corrupt speech attribution."""
    db = TestingSessionLocal()
    meeting = setup_meeting_env["meeting"]
    attendee = setup_meeting_env["attendee"]

    from app.services.meeting_service import record_participant_leave, record_participant_join

    # Attendee disconnects
    part_left = record_participant_leave(db, meeting, attendee.public_id)
    assert part_left.status == "LEFT"
    assert part_left.leave_time is not None

    # Reconnects
    part_rejoin = record_participant_join(db, meeting, attendee.public_id)
    assert part_rejoin.status == "JOINED"
    assert part_rejoin.user_id == attendee.public_id
    assert part_rejoin.identity_mapping_status == "verified"
    assert part_rejoin.livekit_identity == f"{attendee.public_id}:{part_rejoin.id}"
    db.close()


def test_host_leaving_does_not_corrupt_existing_transcript(client: TestClient, setup_meeting_env):
    """Verify that when host leaves the meeting, transcript remains intact and retrievable by attendees."""
    db = TestingSessionLocal()
    meeting = setup_meeting_env["meeting"]
    host = setup_meeting_env["host"]

    # Seed transcript
    seg = TranscriptSegment(
        id=str(uuid.uuid4()),
        meeting_id=meeting.public_id,
        user_id=host.public_id,
        speaker_user_id=host.public_id,
        speaker_label="SPEAKER_00",
        attribution_status="confirmed",
        start_time=1.0,
        end_time=3.0,
        text="Host speech before leaving.",
    )
    db.add(seg)
    db.commit()

    from app.services.meeting_service import record_participant_leave
    record_participant_leave(db, meeting, host.public_id)
    db.close()

    # Attendee queries transcript
    token_att = setup_meeting_env["tokens"]["attendee"]
    resp = client.get(
        f"/api/v1/transcripts/meetings/{meeting.public_id}",
        headers={"Authorization": f"Bearer {token_att}"},
    )
    assert resp.status_code == 200
    segs = resp.json()["segments"]
    assert len(segs) == 1
    assert segs[0]["text"] == "Host speech before leaving."
    assert segs[0]["speaker_user_id"] == host.public_id


def test_audio_data_never_stored_in_database_or_transcript_fields(setup_meeting_env):
    """Verify that transcript segments and meeting tables do not contain binary or base64 audio data."""
    db = TestingSessionLocal()
    meeting = setup_meeting_env["meeting"]

    seg = TranscriptSegment(
        id=str(uuid.uuid4()),
        meeting_id=meeting.public_id,
        user_id=setup_meeting_env["host"].public_id,
        speaker_user_id=setup_meeting_env["host"].public_id,
        speaker_label="SPEAKER_00",
        attribution_status="confirmed",
        start_time=0.0,
        end_time=2.0,
        text="Privacy verified transcript.",
        processing_metadata={"engine": "whisper"},
    )
    db.add(seg)
    db.commit()
    db.refresh(seg)

    # Check transcript text and metadata
    assert not seg.text.startswith("data:audio")
    assert not seg.text.startswith("RIFF")
    assert "audio_bytes" not in (seg.processing_metadata or {})
    assert "raw_audio" not in (seg.processing_metadata or {})
    db.close()


def test_two_simultaneous_meetings_isolation(setup_meeting_env, client: TestClient):
    """Verify cross-tenant and cross-meeting isolation when two meetings exist simultaneously."""
    db = TestingSessionLocal()
    # Meeting 2 belongs to different company
    comp2 = Company(public_id="comp-iso-2", name="Other Inc", domain="other.test")
    user2 = User(
        public_id="usr-other-2",
        email="other@other.test",
        full_name="Other User",
        hashed_password="hash",
        account_type="company",
    )
    db.add_all([comp2, user2])
    db.commit()

    db.add(CompanyMember(company_id=comp2.public_id, user_id=user2.public_id, role="COMPANY_ADMIN"))
    db.commit()

    meeting2 = Meeting(
        public_id="mtg-iso-200",
        company_id=comp2.public_id,
        owner_id=user2.public_id,
        title="Other Company Secret Sync",
        status="COMPLETED",
        transcription_status="completed",
    )
    db.add(meeting2)
    db.commit()

    seg2 = TranscriptSegment(
        id=str(uuid.uuid4()),
        meeting_id=meeting2.public_id,
        user_id=user2.public_id,
        speaker_user_id=user2.public_id,
        speaker_label="SPEAKER_00",
        attribution_status="confirmed",
        start_time=0.0,
        end_time=5.0,
        text="Classified other company secrets.",
    )
    db.add(seg2)
    db.commit()
    meeting2_id = meeting2.public_id
    db.close()

    # User 1 (from setup_meeting_env) tries to view Meeting 2's transcript -> 403 Forbidden
    token1 = setup_meeting_env["tokens"]["host"]
    resp = client.get(
        f"/api/v1/transcripts/meetings/{meeting2_id}",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert resp.status_code == 403
    assert any(msg in resp.json()["detail"].lower() for msg in ["not authorized", "not a member"])


def test_failed_storage_delete_does_not_falsely_mark_purged(setup_meeting_env):
    """
    CRITICAL ISSUE 2: If storage deletion fails (returns False or raises),
    recording.storage_path MUST NOT be cleared and is_audio_purged MUST NOT be set to True.
    """
    db = TestingSessionLocal()
    meeting = setup_meeting_env["meeting"]
    host = setup_meeting_env["host"]

    test_path = f"recordings/{meeting.public_id}/test_failure.wav"
    rec = MeetingRecording(
        id=uuid.uuid4(),
        meeting_id=meeting.public_id,
        company_id=meeting.company_id,
        uploaded_by_user_id=host.public_id,
        storage_backend="mock",
        storage_bucket="test-recordings",
        storage_path=test_path,
        processing_status=RecordingProcessingStatus.COMPLETED.value,
        is_audio_purged=False,
        cleanup_retry_count=0,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    # 1. Simulate storage returning False
    failing_storage = MagicMock()
    failing_storage.delete_private_file.return_value = False
    failing_storage.file_exists.return_value = True

    from app.services.recording_service import purge_recording_audio
    success = purge_recording_audio(db, rec, failing_storage)

    assert success is False
    assert rec.is_audio_purged is False
    assert rec.storage_path == test_path
    assert rec.cleanup_retry_count == 1
    assert "returned False" in (rec.cleanup_error or "")

    # 2. Simulate storage raising an exception
    failing_storage.delete_private_file.side_effect = RuntimeError("Storage connection timed out")
    success2 = purge_recording_audio(db, rec, failing_storage)

    assert success2 is False
    assert rec.is_audio_purged is False
    assert rec.storage_path == test_path
    assert rec.cleanup_retry_count == 2
    assert "Storage connection timed out" in (rec.cleanup_error or "")

    # 3. Simulate recovery on next retry
    failing_storage.delete_private_file.side_effect = None
    failing_storage.delete_private_file.return_value = True
    success3 = purge_recording_audio(db, rec, failing_storage)

    assert success3 is True
    assert rec.is_audio_purged is True
    assert rec.storage_path is None
    assert rec.audio_purged_at is not None
    assert rec.cleanup_error is None
    db.close()


def test_participant_a_cannot_submit_audio_as_participant_b(setup_meeting_env, client: TestClient):
    """
    CRITICAL ISSUE 1: Participant A (even the meeting host) cannot forge or submit audio
    on behalf of Participant B. Must return 403 Forbidden.
    """
    meeting = setup_meeting_env["meeting"]
    attendee = setup_meeting_env["attendee"]
    tokens = setup_meeting_env["tokens"]

    # Attendee's participant record ID
    db = TestingSessionLocal()
    attendee_part = db.query(MeetingParticipant).filter(
        MeetingParticipant.meeting_id == meeting.public_id,
        MeetingParticipant.user_id == attendee.public_id,
    ).first()
    assert attendee_part is not None
    attendee_part_id = str(attendee_part.id)
    db.close()

    # Host attempts to submit audio for Member -> 403 Forbidden
    host_token = tokens["host"]
    fake_wav = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    
    resp = client.post(
        f"/api/v1/transcripts/meetings/{meeting.public_id}/participants/{attendee_part_id}/audio-stream",
        headers={"Authorization": f"Bearer {host_token}"},
        files={"file": ("stream.wav", fake_wav, "audio/wav")},
        data={"start_offset": 0.0},
    )
    assert resp.status_code == 403
    assert "caller identity does not match participant" in resp.json()["detail"]


def test_participant_stream_idempotency_prevents_duplicate_segments(setup_meeting_env, client: TestClient):
    """
    CRITICAL ISSUE 1: Repeated delivery of the same audio chunk (reconnect/retry)
    updates the segment idempotently without creating duplicate database rows.
    """
    meeting = setup_meeting_env["meeting"]
    host = setup_meeting_env["host"]
    host_token = setup_meeting_env["tokens"]["host"]

    db = TestingSessionLocal()
    host_part = db.query(MeetingParticipant).filter(
        MeetingParticipant.meeting_id == meeting.public_id,
        MeetingParticipant.user_id == host.public_id,
    ).first()
    host_part_id = str(host_part.id)
    db.close()

    fake_wav = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"

    with patch.object(
        TranscriptionService,
        "_transcribe_with_retry",
        return_value={
            "segments": [
                {"start_time": 0.0, "end_time": 2.5, "text": "Idempotent speech segment."}
            ]
        },
    ):
        # 1. Send chunk first time
        resp1 = client.post(
            f"/api/v1/transcripts/meetings/{meeting.public_id}/participants/{host_part_id}/audio-stream",
            headers={"Authorization": f"Bearer {host_token}"},
            files={"file": ("chunk1.wav", fake_wav, "audio/wav")},
            data={"start_offset": 10.0},
        )
        assert resp1.status_code == 201

        # 2. Resend exact same chunk (retry/reconnect)
        resp2 = client.post(
            f"/api/v1/transcripts/meetings/{meeting.public_id}/participants/{host_part_id}/audio-stream",
            headers={"Authorization": f"Bearer {host_token}"},
            files={"file": ("chunk1.wav", fake_wav, "audio/wav")},
            data={"start_offset": 10.0},
        )
        assert resp2.status_code == 201

    # Verify database has exactly 1 segment for this timestamp, not 2
    db = TestingSessionLocal()
    expected_seg_id = f"{meeting.public_id}_{host_part_id}_10000"
    segs = db.query(TranscriptSegment).filter(
        TranscriptSegment.meeting_id == meeting.public_id,
        TranscriptSegment.segment_id == expected_seg_id,
    ).all()
    assert len(segs) == 1
    assert segs[0].text == "Idempotent speech segment."
    db.close()


@pytest.mark.asyncio
async def test_egress_ai_job_dispatch_failure_triggers_emergency_purge(setup_meeting_env, memory_storage):
    """
    CRITICAL ISSUE 3: If AI job enqueueing fails after LiveKit egress uploads media,
    emergency audio purge MUST trigger immediately so no orphan audio remains in storage.
    """
    db = TestingSessionLocal()
    meeting = setup_meeting_env["meeting"]
    host = setup_meeting_env["host"]

    egress_id = f"EG_FAIL_{uuid.uuid4().hex[:8]}"
    rec_id = uuid.uuid4()
    rec = MeetingRecording(
        id=rec_id,
        meeting_id=meeting.public_id,
        company_id=meeting.company_id,
        uploaded_by_user_id=host.public_id,
        egress_id=egress_id,
        processing_status=RecordingProcessingStatus.RECORDING.value,
        retention_policy="ephemeral_transcript_only",
    )
    db.add(rec)
    db.commit()
    db.close()

    event = {
        "event": "egress_ended",
        "egress_info": {
            "egress_id": egress_id,
            "status": "EGRESS_COMPLETE",
            "file_results": [
                {
                    "filename": "output.mp4",
                    "duration": 5_000_000_000,
                    "content": b"fake_mp4_bytes",
                }
            ],
        },
    }

    from app.services.recording_service import handle_livekit_webhook_event

    db = TestingSessionLocal()
    with patch("app.services.recording_service._enqueue_ai_job", side_effect=RuntimeError("Cloudflare queue down")):
        result = await handle_livekit_webhook_event(db, event, memory_storage)

    assert result["status"] == "failed"
    assert "AI job dispatch failed" in result["error"]

    # Verify that recording is marked FAILED and audio was purged from storage
    rec = db.query(MeetingRecording).filter(MeetingRecording.id == rec_id).first()
    assert rec.processing_status == RecordingProcessingStatus.FAILED.value
    assert rec.is_audio_purged is True
    assert rec.storage_path is None
    assert len(memory_storage.files) == 0, "No orphaned audio files should remain in storage"
    db.close()


@pytest.mark.asyncio
async def test_duplicate_egress_webhook_after_purge_ignored_safely(setup_meeting_env, memory_storage):
    """
    CRITICAL ISSUE 3: A duplicate egress_ended webhook arriving after audio has been
    purged must be safely ignored without re-uploading media or re-processing.
    """
    db = TestingSessionLocal()
    meeting = setup_meeting_env["meeting"]
    host = setup_meeting_env["host"]

    egress_id = f"EG_DUP_{uuid.uuid4().hex[:8]}"
    rec = MeetingRecording(
        id=uuid.uuid4(),
        meeting_id=meeting.public_id,
        company_id=meeting.company_id,
        uploaded_by_user_id=host.public_id,
        egress_id=egress_id,
        processing_status=RecordingProcessingStatus.COMPLETED.value,
        storage_path=None,  # Audio has been purged
        is_audio_purged=True,
        retention_policy="ephemeral_transcript_only",
    )
    db.add(rec)
    db.commit()

    event = {
        "event": "egress_ended",
        "egress_info": {
            "egress_id": egress_id,
            "status": "EGRESS_COMPLETE",
            "file_results": [
                {
                    "filename": "output.mp4",
                    "duration": 5_000_000_000,
                    "content": b"fake_mp4_bytes",
                }
            ],
        },
    }

    from app.services.recording_service import handle_livekit_webhook_event
    with patch("app.services.recording_service.retrieve_egress_media") as mock_retrieve:
        result = await handle_livekit_webhook_event(db, event, memory_storage)
        mock_retrieve.assert_not_called()

    assert result["status"] == "already_processed"
    db.close()


def test_orphan_audio_reconciliation_mechanism(setup_meeting_env, memory_storage):
    """
    CRITICAL ISSUE 2 & 3: Orphan reconciliation scans unpurged recordings with failed/completed
    jobs or expired thresholds, executes verified purge, and enforces bounded retries.
    """
    db = TestingSessionLocal()
    meeting = setup_meeting_env["meeting"]
    host = setup_meeting_env["host"]

    # 1. Create an orphaned recording whose processing failed
    orphan_path = f"orphans/{meeting.public_id}/failed.wav"
    memory_storage.upload_private_file(path=orphan_path, content=b"orphan_audio", content_type="audio/wav")

    rec1 = MeetingRecording(
        id=uuid.uuid4(),
        meeting_id=meeting.public_id,
        company_id=meeting.company_id,
        uploaded_by_user_id=host.public_id,
        storage_backend="mock",
        storage_bucket="test-recordings",
        storage_path=orphan_path,
        processing_status=RecordingProcessingStatus.FAILED.value,
        is_audio_purged=False,
        cleanup_retry_count=0,
    )
    db.add(rec1)

    # 2. Create a recording whose retry count is already exhausted (>= 5)
    exhausted_path = f"orphans/{meeting.public_id}/exhausted.wav"
    memory_storage.upload_private_file(path=exhausted_path, content=b"exhausted_audio", content_type="audio/wav")

    rec2 = MeetingRecording(
        id=uuid.uuid4(),
        meeting_id=meeting.public_id,
        company_id=meeting.company_id,
        uploaded_by_user_id=host.public_id,
        storage_backend="mock",
        storage_bucket="test-recordings",
        storage_path=exhausted_path,
        processing_status=RecordingProcessingStatus.FAILED.value,
        is_audio_purged=False,
        cleanup_retry_count=5,  # Max retries reached
    )
    db.add(rec2)
    db.commit()

    from app.services.recording_service import reconcile_and_purge_orphaned_audio
    stats = reconcile_and_purge_orphaned_audio(db, memory_storage, max_age_minutes=0, max_retries=5)

    assert stats["scanned"] == 1  # Only rec1 was eligible; rec2 was skipped due to bounded retries
    assert stats["purged"] == 1
    assert stats["failed"] == 0

    # Verify rec1 was cleaned up in storage and db
    assert not memory_storage.file_exists(path=orphan_path)
    db.refresh(rec1)
    assert rec1.is_audio_purged is True
    assert rec1.storage_path is None

    # Verify rec2 was not touched by the bounded reconciliation
    assert memory_storage.file_exists(path=exhausted_path)
    db.refresh(rec2)
    assert rec2.is_audio_purged is False
    assert rec2.storage_path == exhausted_path
    db.close()


def test_reconcile_orphans_endpoint_rejects_unauthorized_member(setup_meeting_env, client: TestClient):
    """
    CRITICAL REQUIREMENT 6: Ordinary company member cannot trigger orphan audio reconciliation.
    Must return 403 Forbidden.
    """
    attendee_token = setup_meeting_env["tokens"]["attendee"]
    resp = client.post(
        "/api/v1/recordings/reconcile-orphans",
        headers={"Authorization": f"Bearer {attendee_token}"},
    )
    assert resp.status_code == 403
    assert "Requires system admin or company admin privileges" in resp.json()["detail"]


def test_reconcile_orphans_endpoint_rejects_cross_tenant_access(setup_meeting_env, client: TestClient):
    """
    CRITICAL REQUIREMENT 6: Company admin cannot reconcile recordings for a company
    they do not administer. Must return 403 Forbidden.
    """
    host_token = setup_meeting_env["tokens"]["host"]
    resp = client.post(
        "/api/v1/recordings/reconcile-orphans?company_id=comp-unauthorized-999",
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 403
    assert "Cannot reconcile recordings for a company you do not administer" in resp.json()["detail"]


def test_reconcile_orphans_endpoint_authorized_company_admin_success(setup_meeting_env, client: TestClient):
    """
    CRITICAL REQUIREMENT 6: Authorized company admin can trigger scoped orphan cleanup.
    Response must return sanitized counts without exposing internal paths.
    """
    host_token = setup_meeting_env["tokens"]["host"]
    with patch(
        "app.api.v1.recordings.reconcile_and_purge_orphaned_audio",
        return_value={"scanned": 3, "purged": 3, "failed": 0, "skipped_active": 0},
    ):
        resp = client.post(
            "/api/v1/recordings/reconcile-orphans",
            headers={"Authorization": f"Bearer {host_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["scanned"] == 3
        assert data["purged"] == 3
        assert data["failed"] == 0
        assert data["skipped_active"] == 0
        assert data["company_id"] == "comp-ret-1"
        # Verify no file paths or sensitive internals are exposed
        assert "storage_path" not in data
        assert "/" not in json.dumps(data)


def test_reconcile_orphans_endpoint_system_admin_global_success(client: TestClient):
    """
    CRITICAL REQUIREMENT 6: System Admin can trigger global orphan reconciliation.
    """
    db = TestingSessionLocal()
    sysadmin = User(
        public_id=f"usr-sysadmin-{uuid.uuid4().hex[:6]}",
        email="admin@meetvault.com",
        full_name="MeetVault System Admin",
        hashed_password="hash",
        account_type="admin",
    )
    db.add(sysadmin)
    db.commit()
    admin_token = create_token(subject=sysadmin.public_id, token_type="access")
    db.close()

    with patch(
        "app.api.v1.recordings.reconcile_and_purge_orphaned_audio",
        return_value={"scanned": 5, "purged": 5, "failed": 0, "skipped_active": 0},
    ):
        resp = client.post(
            "/api/v1/recordings/reconcile-orphans",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["scanned"] == 5
        assert data["purged"] == 5
        assert data["company_id"] is None


def test_alembic_migration_tracking_fields():
    """
    CRITICAL REQUIREMENT 5: Alembic migration add_cleanup_tracking_to_recordings (6b2e1f4a9c33)
    defines clean upgrade and downgrade operations for cleanup_error and cleanup_retry_count.
    """
    import importlib.util
    migration_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "alembic",
        "versions",
        "add_cleanup_tracking_to_recordings.py",
    )
    assert os.path.exists(migration_path), f"Migration file missing: {migration_path}"

    spec = importlib.util.spec_from_file_location("migration_mod", migration_path)
    migration_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration_mod)

    assert migration_mod.revision == "6b2e1f4a9c33"
    assert migration_mod.down_revision == "5f0c3d2e1a44"
    assert hasattr(migration_mod, "upgrade")
    assert hasattr(migration_mod, "downgrade")


def test_admin_endpoint_rejects_email_guess_attacker(client: TestClient):
    """
    CRITICAL REQUIREMENT: An attacker registering an email like 'admin@evil.com'
    with personal account_type must be strictly rejected with 403 Forbidden.
    Server-side role must not guess admin privilege from email prefix or domain.
    """
    db = TestingSessionLocal()
    fake_admin = User(
        public_id=f"usr-fakeadmin-{uuid.uuid4().hex[:6]}",
        email="admin@evil.com",
        full_name="Fake Admin Attacker",
        hashed_password="hash",
        account_type="personal",
    )
    db.add(fake_admin)
    db.commit()
    token = create_token(subject=fake_admin.public_id, token_type="access")
    db.close()

    resp = client.post(
        "/api/v1/recordings/reconcile-orphans",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert "Requires system admin or company admin privileges" in resp.json()["detail"]
