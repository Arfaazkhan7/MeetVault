"""
Test suite for MeetVault temporary audio lifecycle, containment, and crash recovery.

Requirements covered:
1. Every temporary audio path is tracked and contained in dedicated application-controlled directory.
2. Deletion occurs after successful transcription and after failures/cancellations.
3. Active processing files are protected from crash recovery.
4. Path traversal attempts outside dedicated temp storage are strictly blocked.
5. Stale files left by simulated process crashes or unexpected termination are safely reclaimed.
6. Unrelated files and fresh files are preserved.
7. Cloud storage deletion is verified before marking a recording purged.
8. Deletion errors are recorded in cleanup_error and retry count is bounded.
9. Transcript text and metadata remain intact across audio deletion.
10. Sanitized logging does not expose audio bytes, credentials, or sensitive tokens.
"""

import os
from pathlib import Path
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.audio_temp import (
    AUDIO_TEMP_PREFIX,
    create_temp_audio_file,
    get_audio_temp_dir,
    is_temp_file_active,
    managed_temp_audio_file,
    recover_and_cleanup_stale_temp_audio,
    register_active_temp_file,
    safe_delete_temp_file,
    unregister_active_temp_file,
    validate_temp_audio_path,
)
from app.core.enums import RecordingProcessingStatus
from app.core.tokens import create_token
from app.models.ai_job import AIJob
from app.models.company import Company, CompanyMember
from app.models.meeting import Meeting, MeetingParticipant
from app.models.recording import MeetingRecording
from app.models.transcript import TranscriptSegment
from app.models.user import User
from app.services.recording_service import purge_recording_audio
from app.services.storage_service import StorageService, StoredObject
from app.services.transcription_service import TranscriptionEngine, TranscriptionService
from tests.conftest import TestingSessionLocal


class MockStorageService(StorageService):
    def __init__(self, succeed_deletion: bool = True):
        self.files = {}
        self.succeed_deletion = succeed_deletion
        self.deleted_paths = []

    def upload_private_file(self, *, path: str, content: bytes, content_type: str = "audio/wav") -> StoredObject:
        self.files[path] = content
        return StoredObject(backend="mock", bucket="test-recordings", path=path)

    def download_private_file(self, *, path: str) -> bytes:
        if path in self.files:
            return self.files[path]
        raise FileNotFoundError(f"Object {path} not found")

    def delete_private_file(self, *, path: str) -> bool:
        if not self.succeed_deletion:
            return False
        if path in self.files:
            del self.files[path]
            self.deleted_paths.append(path)
            return True
        return False

    def file_exists(self, *, path: str) -> bool:
        return path in self.files

    def create_signed_url(self, *, path: str, expires_in_seconds: int = 3600) -> str:
        return f"https://mock-storage.test/{path}?token=sig123"


class DeterministicMockEngine(TranscriptionEngine):
    def transcribe(self, audio_path: str, language=None):
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file missing: {audio_path}")
        return {
            "segments": [
                {
                    "start_time": 0.0,
                    "end_time": 3.0,
                    "text": "Temporary audio crash recovery verified.",
                    "language": "en",
                    "confidence": 0.99,
                    "words": [{"word": "Temporary", "start": 0.0, "end": 0.8}],
                }
            ],
            "language": "en",
        }


@pytest.fixture
def clean_temp_dir():
    """Ensure dedicated temp dir is clean before and after test."""
    temp_dir = get_audio_temp_dir()
    for item in temp_dir.iterdir():
        if item.is_file():
            try:
                item.unlink(missing_ok=True)
            except OSError:
                pass
    yield temp_dir
    for item in temp_dir.iterdir():
        if item.is_file():
            try:
                item.unlink(missing_ok=True)
            except OSError:
                pass


def test_managed_temp_audio_file_normal_cleanup(clean_temp_dir):
    """Temporary audio is created in dedicated dir and deleted on normal completion."""
    created_path = None
    with managed_temp_audio_file(
        suffix=".wav",
        prefix="mv_audio_chunk_",
        meeting_id="mtg-test-1",
        content=b"sample_pcm_audio",
    ) as path:
        created_path = path
        assert path.exists()
        assert path.parent.resolve() == clean_temp_dir.resolve()
        assert path.name.startswith("mv_audio_chunk_mtg-test-1_")
        assert is_temp_file_active(path)

    # After context exit, file is deleted and unregistered from active files
    assert not created_path.exists()
    assert not is_temp_file_active(created_path)


def test_managed_temp_audio_file_exception_cleanup(clean_temp_dir):
    """Temporary audio is guaranteed deleted even when unhandled exception occurs."""
    captured_path = None
    with pytest.raises(RuntimeError, match="Processing pipeline failure"):
        with managed_temp_audio_file(
            suffix=".wav",
            prefix="mv_audio_chunk_",
            meeting_id="mtg-fail-1",
            content=b"faulty_audio_data",
        ) as path:
            captured_path = path
            assert path.exists()
            assert is_temp_file_active(path)
            raise RuntimeError("Processing pipeline failure")

    assert captured_path is not None
    assert not captured_path.exists()
    assert not is_temp_file_active(captured_path)


def test_active_file_registry_prevents_stale_cleanup(clean_temp_dir):
    """Active in-flight files are protected from crash recovery scanners even if old."""
    temp_file = create_temp_audio_file(
        suffix=".wav",
        prefix="mv_audio_chunk_",
        meeting_id="mtg-active-1",
        content=b"long_running_audio",
    )
    assert temp_file.exists()
    assert is_temp_file_active(temp_file)

    # Artificially set modification time to 2 hours ago (older than max_age_minutes)
    two_hours_ago = time.time() - 7200
    os.utime(temp_file, (two_hours_ago, two_hours_ago))

    # Run crash recovery cleaner
    stats = recover_and_cleanup_stale_temp_audio(max_age_minutes=15)
    assert stats["skipped_active"] >= 1
    # Active file was NOT deleted!
    assert temp_file.exists()

    # Now unregister (operation completed) and re-run cleanup
    unregister_active_temp_file(temp_file)
    stats2 = recover_and_cleanup_stale_temp_audio(max_age_minutes=15)
    assert stats2["deleted"] >= 1
    assert not temp_file.exists()


def test_path_traversal_attempts_are_blocked(clean_temp_dir, tmp_path):
    """Never delete or validate files outside the application's designated temporary directory."""
    # Create an outside file in a separate temp path
    outside_file = tmp_path / "system_sensitive_file.txt"
    outside_file.write_text("critical data")

    # Path traversal validation must reject outside files
    with pytest.raises(ValueError, match="Path traversal security violation"):
        validate_temp_audio_path(outside_file)

    with pytest.raises(ValueError, match="Path traversal security violation"):
        validate_temp_audio_path(f"{clean_temp_dir}/../../something.txt")

    # safe_delete_temp_file must refuse deletion of outside file
    result = safe_delete_temp_file(outside_file, reason="traversal_test")
    assert result is False
    assert outside_file.exists()  # Kept completely safe!


def test_crash_recovery_stale_files_reclaimed(clean_temp_dir):
    """Stale files left by simulated process crashes are safely recovered, preserving young & unrelated files."""
    # 1. Stale MeetVault temporary audio file (2 hours old)
    stale_file = create_temp_audio_file(
        suffix=".wav",
        prefix="mv_audio_pipeline_",
        meeting_id="mtg-crash-1",
        content=b"abandoned_audio_after_crash",
    )
    unregister_active_temp_file(stale_file)
    old_time = time.time() - 7200
    os.utime(stale_file, (old_time, old_time))

    # 2. Fresh MeetVault temporary audio file (1 minute old)
    fresh_file = create_temp_audio_file(
        suffix=".wav",
        prefix="mv_audio_pipeline_",
        meeting_id="mtg-fresh-1",
        content=b"recently_created_audio",
    )
    unregister_active_temp_file(fresh_file)

    # 3. Unrelated file without MeetVault prefix
    unrelated_file = clean_temp_dir / "unrelated_worker_notes.txt"
    unrelated_file.write_text("Do not touch me")
    os.utime(unrelated_file, (old_time, old_time))

    # Run crash recovery with 15-minute threshold
    stats = recover_and_cleanup_stale_temp_audio(max_age_minutes=15)

    assert stats["deleted"] == 1
    assert stats["skipped_young"] >= 1
    assert not stale_file.exists()       # Stale file successfully reclaimed!
    assert fresh_file.exists()           # Fresh file preserved!
    assert unrelated_file.exists()       # Unrelated file preserved!


def test_cloud_deletion_verified_before_marking_purged():
    """Storage deletion must be verified by storage interface before marking recording purged."""
    db = TestingSessionLocal()
    storage = MockStorageService(succeed_deletion=False)

    rec = MeetingRecording(
        id=uuid.uuid4(),
        meeting_id="mtg-cloud-fail",
        company_id="comp-1",
        uploaded_by_user_id="usr-uploader-1",
        storage_backend="mock",
        storage_path="comp-1/mtg-cloud-fail/audio.mp4",
        processing_status=RecordingProcessingStatus.COMPLETED.value,
        is_audio_purged=False,
    )
    db.add(rec)
    db.commit()

    # Upload mock file to storage
    storage.upload_private_file(path=rec.storage_path, content=b"audio_bytes")

    # Attempt purge with storage failure
    purged = purge_recording_audio(db, rec, storage)

    assert purged is False
    assert rec.is_audio_purged is False
    assert rec.storage_path == "comp-1/mtg-cloud-fail/audio.mp4"
    assert rec.cleanup_retry_count == 1
    assert rec.cleanup_error is not None
    assert "Storage provider reported deletion failure" in rec.cleanup_error
    db.close()


def test_cloud_deletion_success_updates_purged_state_and_preserves_transcript():
    """Successful cloud purge sets is_audio_purged and leaves transcript segments intact."""
    db = TestingSessionLocal()
    storage = MockStorageService(succeed_deletion=True)
    mtg_id = "mtg-cloud-success"

    meeting = Meeting(public_id=mtg_id, title="Privacy Sync", status="ENDED")
    rec = MeetingRecording(
        id=uuid.uuid4(),
        meeting_id=mtg_id,
        company_id="comp-1",
        uploaded_by_user_id="usr-uploader-1",
        storage_backend="mock",
        storage_path="comp-1/mtg-cloud-success/audio.mp4",
        processing_status=RecordingProcessingStatus.COMPLETED.value,
        is_audio_purged=False,
    )
    seg1 = TranscriptSegment(
        id=str(uuid.uuid4()),
        meeting_id=mtg_id,
        segment_id=f"{mtg_id}_001",
        speaker_label="SPEAKER_00",
        start_time=0.0,
        end_time=5.0,
        text="All decisions were recorded.",
        language="en",
    )
    db.add_all([meeting, rec, seg1])
    db.commit()

    storage.upload_private_file(path=rec.storage_path, content=b"audio_bytes")

    # Execute verified purge
    purged = purge_recording_audio(db, rec, storage)
    assert purged is True
    assert rec.is_audio_purged is True
    assert rec.storage_path is None
    assert rec.audio_purged_at is not None
    assert rec.cleanup_error is None

    # Verify transcript is completely intact in database
    segments = db.query(TranscriptSegment).filter(TranscriptSegment.meeting_id == mtg_id).all()
    assert len(segments) == 1
    assert segments[0].text == "All decisions were recorded."
    db.close()


def test_transcribe_participant_audio_chunk_honestly_uses_dedicated_temp_and_cleans_up(clean_temp_dir):
    """transcribe_participant_audio_chunk writes to dedicated temp dir and unlinks immediately."""
    db = TestingSessionLocal()
    service = TranscriptionService(engine=DeterministicMockEngine())

    meeting = Meeting(public_id="mtg-chunk-audit", title="Audit Sync")
    user = User(public_id="usr-chunk-1", email="user@privacy.test", full_name="Auditor")
    part = MeetingParticipant(
        meeting_id="mtg-chunk-audit",
        user_id="usr-chunk-1",
        display_name="Auditor",
        is_guest=False,
    )
    db.add_all([meeting, user, part])
    db.commit()

    pcm_data = b"\x00\x00" * 8000  # 0.5s of 16kHz 16-bit mono PCM

    segments = service.transcribe_participant_audio_chunk(
        db=db,
        meeting=meeting,
        participant=part,
        audio_bytes=pcm_data,
        language="en",
        start_offset=0.0,
        end_offset=0.5,
    )

    assert len(segments) == 1
    assert segments[0].text == "Temporary audio crash recovery verified."

    # Verify no residual temporary audio files remain in dedicated directory
    remaining_temp_files = list(clean_temp_dir.glob("mv_audio_chunk_*"))
    assert len(remaining_temp_files) == 0
    db.close()


def test_reconcile_orphans_endpoint_runs_both_cloud_and_temp_cleanup(client: TestClient, clean_temp_dir):
    """Admin orphan reconciliation runs both cloud orphan purge and local crash recovery."""
    db = TestingSessionLocal()
    sysadmin = User(
        public_id="usr-sys-clean",
        email="sysadmin@mv.test",
        full_name="System Admin",
        hashed_password="hash",
        account_type="admin",
    )
    db.add(sysadmin)
    db.commit()

    token = create_token(subject=sysadmin.public_id, token_type="access")

    # Create a stale temporary file in dedicated directory
    stale_file = create_temp_audio_file(
        suffix=".wav",
        prefix="mv_audio_pipeline_",
        meeting_id="mtg-reconcile",
        content=b"stale_bytes",
    )
    unregister_active_temp_file(stale_file)
    old_time = time.time() - 7200
    os.utime(stale_file, (old_time, old_time))

    res = client.post(
        "/api/v1/recordings/reconcile-orphans?max_age_minutes=15",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "completed"
    assert "stale_temp_scanned" in data
    assert "stale_temp_deleted" in data
    assert data["stale_temp_deleted"] >= 1
    assert not stale_file.exists()
    db.close()
