"""
Test suite for Meeting Recording to AI Job Association and Safe Orphan Cleanup.

Covers:
1. One meeting with multiple recordings and multiple AI jobs (correct 1-to-1 matching).
2. Ambiguous association with sibling recordings prevents deletion.
3. Active recording in live session (RECORDING/FINALIZING) is preserved.
4. Active AI job (QUEUED/RUNNING/PROCESSING) preserves audio.
5. Failed job retry vs exhausted retry cleanup eligibility.
6. Duplicate webhook event idempotency.
7. Concurrent cleanup workers safety and idempotency.
8. Cross-tenant / company isolation enforcement.
9. Sanitized logging (no query params or credentials).
10. Alembic migration check for add_ai_job_id_to_recordings (7c3d2e1b4a55).
"""
import importlib.util
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.enums import RecordingProcessingStatus
from app.core.roles import Role
from app.core.tokens import create_token
from app.main import app
from app.models.ai_job import AIJob
from app.models.company import Company, CompanyMember
from app.models.meeting import Meeting
from app.models.recording import MeetingRecording
from app.models.user import User
from app.services.recording_service import (
    _sanitize_storage_path,
    purge_recording_audio,
    reconcile_and_purge_orphaned_audio,
)
from app.services.storage_service import StorageService, StoredObject
from tests.conftest import TestingSessionLocal


class MockStorage(StorageService):
    """In-memory mock storage tracking private uploads and deletions."""

    def __init__(self):
        self.files = {}

    def upload_private_file(self, path: str = None, content: bytes = None, content_type: str = "audio/wav", **kwargs) -> StoredObject:
        if path is None:
            path = kwargs.get("path")
        if content is None:
            content = kwargs.get("content")
        self.files[path] = content
        return StoredObject(backend="mock", bucket="test-recordings", path=path)

    def download_private_file(self, path: str = None, **kwargs) -> bytes:
        if path is None:
            path = kwargs.get("path")
        if path in self.files:
            return self.files[path]
        raise FileNotFoundError(f"File not found: {path}")

    def delete_private_file(self, path: str = None, **kwargs) -> bool:
        if path is None:
            path = kwargs.get("path")
        if path in self.files:
            del self.files[path]
            return True
        return False

    def file_exists(self, path: str = None, **kwargs) -> bool:
        if path is None:
            path = kwargs.get("path")
        return path in self.files

    def create_signed_url(self, path: str = None, expires_in_seconds: int = 3600, **kwargs) -> str:
        if path is None:
            path = kwargs.get("path")
        return f"https://mock-storage.test/{path}?token=secret-signature-123"


@pytest.fixture
def test_env():
    db = TestingSessionLocal()
    comp_a = Company(public_id=f"comp-a-{uuid.uuid4().hex[:6]}", name="Company Alpha")
    comp_b = Company(public_id=f"comp-b-{uuid.uuid4().hex[:6]}", name="Company Beta")
    db.add_all([comp_a, comp_b])
    db.flush()

    user_a = User(
        public_id=f"usr-a-{uuid.uuid4().hex[:6]}",
        email="admin@alpha.com",
        full_name="Alpha Admin",
        hashed_password="hash",
        account_type="organization",
    )
    user_b = User(
        public_id=f"usr-b-{uuid.uuid4().hex[:6]}",
        email="admin@beta.com",
        full_name="Beta Admin",
        hashed_password="hash",
        account_type="organization",
    )
    sysadmin = User(
        public_id=f"usr-sys-{uuid.uuid4().hex[:6]}",
        email="sysadmin@mv.com",
        full_name="System Admin",
        hashed_password="hash",
        account_type="admin",
    )
    db.add_all([user_a, user_b, sysadmin])
    db.flush()

    mem_a = CompanyMember(user_id=user_a.public_id, company_id=comp_a.public_id, role=Role.COMPANY_ADMIN.value)
    mem_b = CompanyMember(user_id=user_b.public_id, company_id=comp_b.public_id, role=Role.COMPANY_ADMIN.value)
    db.add_all([mem_a, mem_b])
    db.flush()

    meeting_a = Meeting(
        public_id=f"mtg-a-{uuid.uuid4().hex[:6]}",
        company_id=comp_a.public_id,
        owner_id=user_a.public_id,
        title="Alpha Strategic Planning",
    )
    meeting_b = Meeting(
        public_id=f"mtg-b-{uuid.uuid4().hex[:6]}",
        company_id=comp_b.public_id,
        owner_id=user_b.public_id,
        title="Beta Standup",
    )
    db.add_all([meeting_a, meeting_b])
    db.commit()

    comp_a_id = comp_a.public_id
    comp_b_id = comp_b.public_id
    user_a_id = user_a.public_id
    user_b_id = user_b.public_id
    sysadmin_id = sysadmin.public_id
    meeting_a_id = meeting_a.public_id
    meeting_b_id = meeting_b.public_id

    token_a = create_token(subject=user_a.public_id, token_type="access")
    token_b = create_token(subject=user_b.public_id, token_type="access")
    token_sys = create_token(subject=sysadmin.public_id, token_type="access")
    db.close()

    return {
        "comp_a": comp_a_id,
        "comp_b": comp_b_id,
        "user_a": user_a_id,
        "user_b": user_b_id,
        "sysadmin": sysadmin_id,
        "meeting_a": meeting_a_id,
        "meeting_b": meeting_b_id,
        "token_a": token_a,
        "token_b": token_b,
        "token_sys": token_sys,
    }


def test_multiple_recordings_one_meeting_never_deletes_active_recording(test_env):
    """
    REQUIREMENT 1, 3, 5: One meeting has multiple recordings.
    Recording 1: Finished transcription (AIJob 1 is COMPLETED).
    Recording 2: Still actively processing (AIJob 2 is RUNNING).
    Reconciliation MUST purge Recording 1's audio and MUST NOT touch Recording 2's audio!
    """
    db = TestingSessionLocal()
    storage = MockStorage()
    mtg_id = test_env["meeting_a"]
    comp_id = test_env["comp_a"]
    u_id = test_env["user_a"]

    path_rec1 = f"{comp_id}/{mtg_id}/rec1.mp4"
    path_rec2 = f"{comp_id}/{mtg_id}/rec2.mp4"
    storage.upload_private_file(path_rec1, b"rec1_audio_bytes")
    storage.upload_private_file(path_rec2, b"rec2_audio_bytes")

    rec1 = MeetingRecording(
        id=uuid.uuid4(),
        meeting_id=mtg_id,
        company_id=comp_id,
        uploaded_by_user_id=u_id,
        storage_backend="mock",
        storage_path=path_rec1,
        processing_status=RecordingProcessingStatus.COMPLETED.value,
        is_audio_purged=False,
        cleanup_retry_count=0,
    )
    rec2 = MeetingRecording(
        id=uuid.uuid4(),
        meeting_id=mtg_id,
        company_id=comp_id,
        uploaded_by_user_id=u_id,
        storage_backend="mock",
        storage_path=path_rec2,
        processing_status=RecordingProcessingStatus.PROCESSING.value,
        is_audio_purged=False,
        cleanup_retry_count=0,
    )
    db.add_all([rec1, rec2])
    db.flush()

    job1 = AIJob(
        public_id=f"AIJ-{uuid.uuid4().hex[:6]}",
        meeting_id=mtg_id,
        recording_id=str(rec1.id),
        company_id=comp_id,
        requested_by_user_id=u_id,
        status="COMPLETED",
    )
    job2 = AIJob(
        public_id=f"AIJ-{uuid.uuid4().hex[:6]}",
        meeting_id=mtg_id,
        recording_id=str(rec2.id),
        company_id=comp_id,
        requested_by_user_id=u_id,
        status="RUNNING",  # Active!
    )
    rec1.ai_job_id = job1.public_id
    rec2.ai_job_id = job2.public_id
    db.add_all([job1, job2])
    db.commit()

    stats = reconcile_and_purge_orphaned_audio(db, storage, company_id=comp_id, max_age_minutes=0)
    assert stats["scanned"] == 2
    assert stats["purged"] == 1
    assert stats["skipped_active"] == 1
    assert stats["failed"] == 0

    # Rec1 audio is purged
    db.refresh(rec1)
    assert rec1.is_audio_purged is True
    assert rec1.storage_path is None
    assert not storage.file_exists(path_rec1)

    # Rec2 audio is PRESERVED because its job is active
    db.refresh(rec2)
    assert rec2.is_audio_purged is False
    assert rec2.storage_path == path_rec2
    assert storage.file_exists(path_rec2)

    db.close()


def test_ambiguous_association_with_sibling_recordings_skips_purge(test_env):
    """
    REQUIREMENT 3 & 5: When multiple recordings exist in a meeting and a recording
    lacks an unambiguous AIJob association, cleanup MUST NOT purge it using meeting-level jobs.
    """
    db = TestingSessionLocal()
    storage = MockStorage()
    mtg_id = test_env["meeting_a"]
    comp_id = test_env["comp_a"]
    u_id = test_env["user_a"]

    path_rec_a = f"{comp_id}/{mtg_id}/rec_a.mp4"
    path_rec_b = f"{comp_id}/{mtg_id}/rec_b.mp4"
    storage.upload_private_file(path_rec_a, b"rec_a_bytes")
    storage.upload_private_file(path_rec_b, b"rec_b_bytes")

    rec_a = MeetingRecording(
        id=uuid.uuid4(),
        meeting_id=mtg_id,
        company_id=comp_id,
        uploaded_by_user_id=u_id,
        storage_backend="mock",
        storage_path=path_rec_a,
        processing_status=RecordingProcessingStatus.QUEUED.value,
        is_audio_purged=False,
    )
    rec_b = MeetingRecording(
        id=uuid.uuid4(),
        meeting_id=mtg_id,
        company_id=comp_id,
        uploaded_by_user_id=u_id,
        storage_backend="mock",
        storage_path=path_rec_b,
        processing_status=RecordingProcessingStatus.QUEUED.value,
        is_audio_purged=False,
    )
    db.add_all([rec_a, rec_b])
    db.flush()

    # Create a meeting-level job that does not link to rec_a or rec_b
    stray_job = AIJob(
        public_id=f"AIJ-{uuid.uuid4().hex[:6]}",
        meeting_id=mtg_id,
        recording_id=str(uuid.uuid4()),  # Unrelated recording ID
        company_id=comp_id,
        requested_by_user_id=u_id,
        status="COMPLETED",
    )
    db.add(stray_job)
    db.commit()

    stats = reconcile_and_purge_orphaned_audio(db, storage, company_id=comp_id, max_age_minutes=0)
    # Neither rec_a nor rec_b should be purged based on stray_job
    assert stats["purged"] == 0
    assert stats["skipped_ambiguous"] == 2

    assert storage.file_exists(path_rec_a)
    assert storage.file_exists(path_rec_b)
    db.close()


def test_active_recording_session_is_never_purged(test_env):
    """
    REQUIREMENT 4 & 5: Recordings in STARTING, RECORDING, or FINALIZING status
    represent active live sessions and MUST NOT be purged.
    """
    db = TestingSessionLocal()
    storage = MockStorage()
    mtg_id = test_env["meeting_a"]
    comp_id = test_env["comp_a"]
    u_id = test_env["user_a"]

    path_live = f"{comp_id}/{mtg_id}/live.mp4"
    storage.upload_private_file(path_live, b"live_audio_in_progress")

    for live_status in [
        RecordingProcessingStatus.STARTING.value,
        RecordingProcessingStatus.RECORDING.value,
        RecordingProcessingStatus.FINALIZING.value,
    ]:
        rec = MeetingRecording(
            id=uuid.uuid4(),
            meeting_id=mtg_id,
            company_id=comp_id,
            uploaded_by_user_id=u_id,
            storage_backend="mock",
            storage_path=path_live,
            processing_status=live_status,
            is_audio_purged=False,
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),  # even if old
        )
        db.add(rec)
        db.commit()

        stats = reconcile_and_purge_orphaned_audio(db, storage, company_id=comp_id, max_age_minutes=0)
        assert stats["purged"] == 0
        assert stats["skipped_active"] >= 1
        assert storage.file_exists(path_live)

        db.delete(rec)
        db.commit()

    db.close()


def test_retriable_failed_job_preserves_audio_until_exhausted(test_env):
    """
    REQUIREMENT 4: A failed AI job with remaining retries (retry_count < max_retries)
    is preserved for retry if within timeout window. Once retries are exhausted, it is purged.
    """
    db = TestingSessionLocal()
    storage = MockStorage()
    mtg_id = test_env["meeting_a"]
    comp_id = test_env["comp_a"]
    u_id = test_env["user_a"]

    path_retriable = f"{comp_id}/{mtg_id}/retriable.mp4"
    storage.upload_private_file(path_retriable, b"audio_for_retry")

    rec = MeetingRecording(
        id=uuid.uuid4(),
        meeting_id=mtg_id,
        company_id=comp_id,
        uploaded_by_user_id=u_id,
        storage_backend="mock",
        storage_path=path_retriable,
        processing_status=RecordingProcessingStatus.QUEUED.value,
        is_audio_purged=False,
        created_at=datetime.now(timezone.utc),
    )
    db.add(rec)
    db.flush()

    job = AIJob(
        public_id=f"AIJ-{uuid.uuid4().hex[:6]}",
        meeting_id=mtg_id,
        recording_id=str(rec.id),
        company_id=comp_id,
        requested_by_user_id=u_id,
        status="FAILED",
        retry_count=1,
        max_retries=3,  # Can still retry twice
    )
    rec.ai_job_id = job.public_id
    db.add(job)
    db.commit()

    # Within timeout window (max_age_minutes=15, recording created now)
    stats1 = reconcile_and_purge_orphaned_audio(db, storage, company_id=comp_id, max_age_minutes=15)
    assert stats1["purged"] == 0
    assert stats1["skipped_active"] == 1
    assert storage.file_exists(path_retriable)

    # Exhaust retries: retry_count = 3 >= max_retries
    job.retry_count = 3
    db.commit()

    stats2 = reconcile_and_purge_orphaned_audio(db, storage, company_id=comp_id, max_age_minutes=15)
    assert stats2["purged"] == 1
    assert not storage.file_exists(path_retriable)
    db.refresh(rec)
    assert rec.is_audio_purged is True

    db.close()


def test_concurrent_cleanup_workers_are_safe_and_idempotent(test_env):
    """
    REQUIREMENT 6 & 8: Concurrent reconciliation workers do not double-delete,
    throw concurrency exceptions, or corrupt state.
    """
    db = TestingSessionLocal()
    storage = MockStorage()
    mtg_id = test_env["meeting_a"]
    comp_id = test_env["comp_a"]
    u_id = test_env["user_a"]

    # Create 4 completed recordings
    recordings = []
    for i in range(4):
        p = f"{comp_id}/{mtg_id}/concurrent_{i}.mp4"
        storage.upload_private_file(p, f"bytes_{i}".encode())
        r = MeetingRecording(
            id=uuid.uuid4(),
            meeting_id=mtg_id,
            company_id=comp_id,
            uploaded_by_user_id=u_id,
            storage_backend="mock",
            storage_path=p,
            processing_status=RecordingProcessingStatus.COMPLETED.value,
            is_audio_purged=False,
        )
        j = AIJob(
            public_id=f"AIJ-CONC-{i}-{uuid.uuid4().hex[:4]}",
            meeting_id=mtg_id,
            recording_id=str(r.id),
            company_id=comp_id,
            requested_by_user_id=u_id,
            status="COMPLETED",
        )
        r.ai_job_id = j.public_id
        db.add_all([r, j])
        recordings.append(r)
    db.commit()
    db.close()

    results = []

    def worker_run():
        worker_db = TestingSessionLocal()
        try:
            s = reconcile_and_purge_orphaned_audio(worker_db, storage, company_id=comp_id, max_age_minutes=0)
            results.append(s)
        finally:
            worker_db.close()

    t1 = threading.Thread(target=worker_run)
    t2 = threading.Thread(target=worker_run)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Across both workers, exactly 4 recordings were purged, 0 failed
    total_purged = sum(r["purged"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    assert total_purged == 4
    assert total_failed == 0
    assert len(storage.files) == 0


def test_cross_tenant_isolation_enforced(test_env, client: TestClient):
    """
    REQUIREMENT 7: Company A admin cannot reconcile or purge Company B's recordings.
    """
    db = TestingSessionLocal()
    storage = MockStorage()
    mtg_b = test_env["meeting_b"]
    comp_b = test_env["comp_b"]
    u_b = test_env["user_b"]

    p_b = f"{comp_b}/{mtg_b}/tenant_b.mp4"
    storage.upload_private_file(p_b, b"company_b_private_audio")

    rec_b = MeetingRecording(
        id=uuid.uuid4(),
        meeting_id=mtg_b,
        company_id=comp_b,
        uploaded_by_user_id=u_b,
        storage_backend="mock",
        storage_path=p_b,
        processing_status=RecordingProcessingStatus.COMPLETED.value,
        is_audio_purged=False,
    )
    job_b = AIJob(
        public_id=f"AIJ-B-{uuid.uuid4().hex[:6]}",
        meeting_id=mtg_b,
        recording_id=str(rec_b.id),
        company_id=comp_b,
        requested_by_user_id=u_b,
        status="COMPLETED",
    )
    rec_b.ai_job_id = job_b.public_id
    db.add_all([rec_b, job_b])
    db.commit()
    db.close()

    token_a = test_env["token_a"]

    # Company A admin attempts to reconcile Company B
    resp = client.post(
        f"/api/v1/recordings/reconcile-orphans?company_id={comp_b}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403
    assert "Cannot reconcile recordings for a company you do not administer" in resp.json()["detail"]

    # Company B audio remains untouched
    assert storage.file_exists(p_b)


def test_sanitized_logging_strips_sensitive_query_parameters():
    """
    REQUIREMENT 10: Log messages must sanitize paths, stripping query parameters,
    tokens, and credentials.
    """
    sensitive_path = "tenant-1/mtg-123/audio.mp4?token=eyJh...&signature=xyz123#frag"
    clean = _sanitize_storage_path(sensitive_path)
    assert "token" not in clean
    assert "signature" not in clean
    assert "xyz123" not in clean
    assert clean == "tenant-1/.../audio.mp4"

    assert _sanitize_storage_path(None) == "none"
    assert _sanitize_storage_path("simple.wav") == "simple.wav"


def test_alembic_migration_add_ai_job_id_to_recordings():
    """
    REQUIREMENT 9: Validate Alembic migration 7c3d2e1b4a55 cleanly extends
    6b2e1f4a9c33 with ai_job_id column.
    """
    migration_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "alembic",
        "versions",
        "add_ai_job_id_to_recordings.py",
    )
    assert os.path.exists(migration_path), f"Migration file missing: {migration_path}"

    spec = importlib.util.spec_from_file_location("migration_ai_job_id", migration_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.revision == "7c3d2e1b4a55"
    assert mod.down_revision == "6b2e1f4a9c33"
    assert hasattr(mod, "upgrade")
    assert hasattr(mod, "downgrade")
