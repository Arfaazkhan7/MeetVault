import json
import pytest
from app.services.storage_service import StoredObject, get_storage_service


class MockStorageService:
    def __init__(self, should_fail=False):
        self.objects = {}
        self.should_fail = should_fail

    def upload_private_file(self, *, path: str, content: bytes, content_type: str) -> StoredObject:
        if self.should_fail:
            raise RuntimeError("Storage backend connection timed out")
        self.objects[path] = {"content": content, "content_type": content_type}
        return StoredObject(backend="supabase", bucket="meeting-recordings", path=path)

    def create_signed_url(self, *, path: str, expires_in_seconds: int) -> str:
        return f"https://mock-supabase.test/storage/v1/object/sign/{path}?expires={expires_in_seconds}"

    def download_private_file(self, *, path: str) -> bytes:
        if path not in self.objects:
            raise FileNotFoundError(f"Object {path} not found")
        return self.objects[path]["content"]


mock_storage = MockStorageService()


def register(client, email, name="Test User", password="StrongPass1"):
    r = client.post("/api/v1/auth/register", json={
        "full_name": name,
        "email": email,
        "password": password,
    })
    assert r.status_code == 201, r.text
    return r.json()


def login(client, email, password="StrongPass1"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def setup_meeting_fixture(client):
    host = register(client, "auto-host@example.com", "Auto Rec Host")
    host_token = login(client, "auto-host@example.com")

    attendee = register(client, "auto-attendee@example.com", "Auto Rec Attendee")
    attendee_token = login(client, "auto-attendee@example.com")

    outsider = register(client, "auto-outsider@example.com", "Auto Rec Outsider")
    outsider_token = login(client, "auto-outsider@example.com")

    # Create meeting
    meeting = client.post(
        "/api/v1/meetings/personal",
        json={"title": "Automatic Recording Sync"},
        headers=auth_headers(host_token),
    ).json()

    meeting_id = meeting["public_id"]

    # Host connects to room
    client.post(
        f"/api/v1/meetings/{meeting_id}/room/connect",
        headers=auth_headers(host_token),
    )
    # Attendee connects to room
    client.post(
        f"/api/v1/meetings/{meeting_id}/room/connect",
        headers=auth_headers(attendee_token),
    )

    return {
        "host": host,
        "host_token": host_token,
        "attendee": attendee,
        "attendee_token": attendee_token,
        "outsider": outsider,
        "outsider_token": outsider_token,
        "meeting": meeting,
        "meeting_id": meeting_id,
    }


def test_auto_recording_start_and_idempotency(client):
    data = setup_meeting_fixture(client)
    meeting_id = data["meeting_id"]

    # 1. Host starts automatic recording session
    r1 = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/auto/start",
        headers=auth_headers(data["host_token"]),
    )
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["processing_status"] == "RECORDING"
    assert body1["session_id"] is not None
    assert body1["session_id"].startswith("REC-SESS-")
    assert body1["meeting_id"] == meeting_id

    # 2. Duplicate start returns the exact same recording session (idempotency)
    r2 = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/auto/start",
        headers=auth_headers(data["host_token"]),
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["id"] == body1["id"]
    assert body2["session_id"] == body1["session_id"]


def test_auto_recording_stop_transitions_to_finalizing(client):
    data = setup_meeting_fixture(client)
    meeting_id = data["meeting_id"]

    # Start recording
    client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/auto/start",
        headers=auth_headers(data["host_token"]),
    )

    # Stop recording
    r_stop = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/auto/stop",
        headers=auth_headers(data["host_token"]),
    )
    assert r_stop.status_code == 200, r_stop.text
    body_stop = r_stop.json()
    assert body_stop["processing_status"] == "FINALIZING"


def test_auto_recording_finalization_with_mixed_audio_dispatches_ai_job(client, monkeypatch):
    monkeypatch.setattr("app.services.recording_service._enqueue_ai_job", lambda _db, _job_id: None)
    client.app.dependency_overrides[get_storage_service] = lambda: mock_storage

    data = setup_meeting_fixture(client)
    meeting_id = data["meeting_id"]

    # 1. Start session
    start_res = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/auto/start",
        headers=auth_headers(data["host_token"]),
    ).json()
    session_id = start_res["session_id"]

    # 2. Finalize mixed audio
    fake_mixed_audio = b"\x1a\x45\xdf\xa3WebM-Mixed-Audio-Tracks-Local-And-Remote"
    response = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings",
        headers=auth_headers(data["host_token"]),
        data={"duration_seconds": "120", "session_id": session_id},
        files={"file": ("meeting-mixed.webm", fake_mixed_audio, "audio/webm")},
    )
    client.app.dependency_overrides.pop(get_storage_service, None)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["processing_status"] == "QUEUED"
    assert body["duration_seconds"] == 120
    assert body["file_size_bytes"] == len(fake_mixed_audio)
    assert body["ai_job_id"] is not None
    assert body["ai_job_id"].startswith("AIJ-")
    assert body["storage_path"] in mock_storage.objects

    # 3. Verify AI Job in database
    jobs = client.get(
        f"/api/v1/meetings/{meeting_id}/ai-jobs",
        headers=auth_headers(data["host_token"]),
    )
    assert jobs.status_code == 200
    job_list = jobs.json()
    assert len(job_list) == 1
    assert job_list[0]["status"] == "QUEUED"
    assert job_list[0]["recording_id"] == body["id"]


def test_duplicate_finalization_is_idempotent(client, monkeypatch):
    monkeypatch.setattr("app.services.recording_service._enqueue_ai_job", lambda _db, _job_id: None)
    client.app.dependency_overrides[get_storage_service] = lambda: mock_storage

    data = setup_meeting_fixture(client)
    meeting_id = data["meeting_id"]

    start_res = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/auto/start",
        headers=auth_headers(data["host_token"]),
    ).json()
    session_id = start_res["session_id"]

    audio_bytes = b"Audio-Payload-12345"

    # First upload
    r1 = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings",
        headers=auth_headers(data["host_token"]),
        data={"duration_seconds": "45", "session_id": session_id},
        files={"file": ("meeting.webm", audio_bytes, "audio/webm")},
    )
    assert r1.status_code == 201

    # Duplicate upload with same session
    r2 = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings",
        headers=auth_headers(data["host_token"]),
        data={"duration_seconds": "45", "session_id": session_id},
        files={"file": ("meeting.webm", audio_bytes, "audio/webm")},
    )
    client.app.dependency_overrides.pop(get_storage_service, None)

    assert r2.status_code in (200, 201)
    body1 = r1.json()
    body2 = r2.json()
    assert body2["id"] == body1["id"]
    assert body2["ai_job_id"] == body1["ai_job_id"]

    # Verify only ONE AI job was created
    jobs = client.get(
        f"/api/v1/meetings/{meeting_id}/ai-jobs",
        headers=auth_headers(data["host_token"]),
    ).json()
    assert len(jobs) == 1


def test_finalization_rejects_empty_media(client):
    client.app.dependency_overrides[get_storage_service] = lambda: mock_storage
    data = setup_meeting_fixture(client)
    meeting_id = data["meeting_id"]

    response = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings",
        headers=auth_headers(data["host_token"]),
        files={"file": ("empty.webm", b"", "audio/webm")},
    )
    client.app.dependency_overrides.pop(get_storage_service, None)
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_finalization_rejects_unsupported_type(client):
    client.app.dependency_overrides[get_storage_service] = lambda: mock_storage
    data = setup_meeting_fixture(client)
    meeting_id = data["meeting_id"]

    response = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings",
        headers=auth_headers(data["host_token"]),
        files={"file": ("document.pdf", b"%PDF-1.4", "application/pdf")},
    )
    client.app.dependency_overrides.pop(get_storage_service, None)
    assert response.status_code == 400
    assert "unsupported" in response.json()["detail"].lower()


def test_storage_failure_marks_recording_failed(client):
    failing_storage = MockStorageService(should_fail=True)
    client.app.dependency_overrides[get_storage_service] = lambda: failing_storage

    data = setup_meeting_fixture(client)
    meeting_id = data["meeting_id"]

    # Start session
    client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/auto/start",
        headers=auth_headers(data["host_token"]),
    )

    # Attempt finalization with failing storage
    response = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings",
        headers=auth_headers(data["host_token"]),
        files={"file": ("test.webm", b"bytes", "audio/webm")},
    )
    client.app.dependency_overrides.pop(get_storage_service, None)

    assert response.status_code == 500
    assert "Failed to store recording artifact" in response.json()["detail"]


def test_non_host_cannot_start_stop_or_finalize(client):
    client.app.dependency_overrides[get_storage_service] = lambda: mock_storage
    data = setup_meeting_fixture(client)
    meeting_id = data["meeting_id"]

    # Attendee attempts start
    r_start = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/auto/start",
        headers=auth_headers(data["attendee_token"]),
    )
    assert r_start.status_code == 403

    # Attendee attempts stop
    r_stop = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/auto/stop",
        headers=auth_headers(data["attendee_token"]),
    )
    assert r_stop.status_code == 403

    # Attendee attempts upload
    r_upload = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings",
        headers=auth_headers(data["attendee_token"]),
        files={"file": ("test.webm", b"bytes", "audio/webm")},
    )
    assert r_upload.status_code == 403

    # Outsider attempts
    r_outsider = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/auto/start",
        headers=auth_headers(data["outsider_token"]),
    )
    assert r_outsider.status_code == 403

    client.app.dependency_overrides.pop(get_storage_service, None)


def test_livekit_webhook_egress_ended_finalization(client, monkeypatch):
    enqueued_jobs = []
    monkeypatch.setattr("app.services.recording_service._enqueue_ai_job", lambda _db, job_id: enqueued_jobs.append(job_id))
    client.app.dependency_overrides[get_storage_service] = lambda: mock_storage

    data = setup_meeting_fixture(client)
    meeting_id = data["meeting_id"]

    # Start session and inject mock egress_id
    start_res = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/auto/start",
        headers=auth_headers(data["host_token"]),
    ).json()

    from tests.conftest import TestingSessionLocal
    from app.models.recording import MeetingRecording
    from uuid import UUID

    db = TestingSessionLocal()
    rec = db.query(MeetingRecording).filter(MeetingRecording.id == UUID(start_res["id"])).first()
    rec.egress_id = "EG_TEST_12345"
    db.commit()
    db.close()

    # Mock Webhook verification with file_results containing valid audio content
    class MockFileInfo:
        filename = "meeting-output.mp4"
        duration = 90_000_000_000
        size = 1024
        location = ""
        content = b"RIFF....WAVEfmt mock-audio-stream"

    class MockEgressInfo:
        egress_id = "EG_TEST_12345"
        status = "EGRESS_COMPLETE"
        error = None
        duration = 90_000_000_000
        file_results = [MockFileInfo()]

    class MockWebhookEvent:
        event = "egress_ended"
        egress_info = MockEgressInfo()

    monkeypatch.setattr(
        "app.api.v1.recordings.verify_livekit_webhook",
        lambda _body, _auth: MockWebhookEvent()
    )

    # Trigger LiveKit Webhook
    response = client.post(
        "/api/v1/recordings/livekit-webhook",
        headers={"Authorization": "Bearer mock-livekit-token"},
        json={"event": "egress_ended"},
    )
    client.app.dependency_overrides.pop(get_storage_service, None)

    assert response.status_code == 200, response.text
    res_data = response.json()
    assert res_data["status"] == "processed"
    assert "storage_path" in res_data
    assert res_data["storage_path"] is not None

    # Verify recording updated to QUEUED, storage_path persisted, and AI job enqueued
    recordings = client.get(
        f"/api/v1/meetings/{meeting_id}/recordings",
        headers=auth_headers(data["host_token"]),
    ).json()
    assert len(recordings) == 1
    assert recordings[0]["processing_status"] == "QUEUED"
    assert recordings[0]["storage_path"] is not None
    assert recordings[0]["storage_path"] == res_data["storage_path"]
    assert len(enqueued_jobs) == 1


def test_livekit_webhook_missing_output_files_marks_failed(client, monkeypatch):
    enqueued_jobs = []
    monkeypatch.setattr("app.services.recording_service._enqueue_ai_job", lambda _db, job_id: enqueued_jobs.append(job_id))
    client.app.dependency_overrides[get_storage_service] = lambda: mock_storage

    data = setup_meeting_fixture(client)
    meeting_id = data["meeting_id"]

    start_res = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/auto/start",
        headers=auth_headers(data["host_token"]),
    ).json()

    from tests.conftest import TestingSessionLocal
    from app.models.recording import MeetingRecording
    from uuid import UUID

    db = TestingSessionLocal()
    rec = db.query(MeetingRecording).filter(MeetingRecording.id == UUID(start_res["id"])).first()
    rec.egress_id = "EG_TEST_NO_FILES"
    db.commit()
    db.close()

    class MockEgressNoFiles:
        egress_id = "EG_TEST_NO_FILES"
        status = "EGRESS_COMPLETE"
        error = None
        file_results = []

    class MockWebhookEvent:
        event = "egress_ended"
        egress_info = MockEgressNoFiles()

    monkeypatch.setattr(
        "app.api.v1.recordings.verify_livekit_webhook",
        lambda _body, _auth: MockWebhookEvent()
    )

    response = client.post(
        "/api/v1/recordings/livekit-webhook",
        headers={"Authorization": "Bearer mock-livekit-token"},
        json={"event": "egress_ended"},
    )
    client.app.dependency_overrides.pop(get_storage_service, None)

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "no output files" in response.json()["error"].lower()
    # Crucially, no unusable AI job should be enqueued
    assert len(enqueued_jobs) == 0


def test_livekit_webhook_media_retrieval_failure_marks_failed(client, monkeypatch):
    enqueued_jobs = []
    monkeypatch.setattr("app.services.recording_service._enqueue_ai_job", lambda _db, job_id: enqueued_jobs.append(job_id))
    client.app.dependency_overrides[get_storage_service] = lambda: mock_storage

    data = setup_meeting_fixture(client)
    meeting_id = data["meeting_id"]

    start_res = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/auto/start",
        headers=auth_headers(data["host_token"]),
    ).json()

    from tests.conftest import TestingSessionLocal
    from app.models.recording import MeetingRecording
    from uuid import UUID

    db = TestingSessionLocal()
    rec = db.query(MeetingRecording).filter(MeetingRecording.id == UUID(start_res["id"])).first()
    rec.egress_id = "EG_TEST_RETRIEVAL_FAIL"
    db.commit()
    db.close()

    class MockFileInfo:
        filename = "nonexistent-cloud-path.mp4"
        location = "s3://nonexistent-bucket/nonexistent-key.mp4"
        duration = 1000

    class MockEgressInfo:
        egress_id = "EG_TEST_RETRIEVAL_FAIL"
        status = "EGRESS_COMPLETE"
        error = None
        file_results = [MockFileInfo()]

    class MockWebhookEvent:
        event = "egress_ended"
        egress_info = MockEgressInfo()

    monkeypatch.setattr(
        "app.api.v1.recordings.verify_livekit_webhook",
        lambda _body, _auth: MockWebhookEvent()
    )

    # Force retrieval failure
    monkeypatch.setattr(
        "app.services.recording_service.retrieve_egress_media",
        lambda _f: (_ for _ in ()).throw(FileNotFoundError("Media output was not found on remote storage")),
    )

    response = client.post(
        "/api/v1/recordings/livekit-webhook",
        headers={"Authorization": "Bearer mock-livekit-token"},
        json={"event": "egress_ended"},
    )
    client.app.dependency_overrides.pop(get_storage_service, None)

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "retrieval failed" in response.json()["error"].lower()
    assert len(enqueued_jobs) == 0


def test_livekit_webhook_storage_failure_marks_failed(client, monkeypatch):
    enqueued_jobs = []
    monkeypatch.setattr("app.services.recording_service._enqueue_ai_job", lambda _db, job_id: enqueued_jobs.append(job_id))

    class FailingStorage:
        def upload_private_file(self, *args, **kwargs):
            raise RuntimeError("Storage bucket unreachable")

    client.app.dependency_overrides[get_storage_service] = lambda: FailingStorage()

    data = setup_meeting_fixture(client)
    meeting_id = data["meeting_id"]

    start_res = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/auto/start",
        headers=auth_headers(data["host_token"]),
    ).json()

    from tests.conftest import TestingSessionLocal
    from app.models.recording import MeetingRecording
    from uuid import UUID

    db = TestingSessionLocal()
    rec = db.query(MeetingRecording).filter(MeetingRecording.id == UUID(start_res["id"])).first()
    rec.egress_id = "EG_TEST_STORAGE_FAIL"
    db.commit()
    db.close()

    class MockFileInfo:
        filename = "valid.mp4"
        content = b"valid bytes"

    class MockEgressInfo:
        egress_id = "EG_TEST_STORAGE_FAIL"
        status = "EGRESS_COMPLETE"
        error = None
        file_results = [MockFileInfo()]

    class MockWebhookEvent:
        event = "egress_ended"
        egress_info = MockEgressInfo()

    monkeypatch.setattr(
        "app.api.v1.recordings.verify_livekit_webhook",
        lambda _body, _auth: MockWebhookEvent()
    )

    response = client.post(
        "/api/v1/recordings/livekit-webhook",
        headers={"Authorization": "Bearer mock-livekit-token"},
        json={"event": "egress_ended"},
    )
    client.app.dependency_overrides.pop(get_storage_service, None)

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "storage upload failed" in response.json()["error"].lower()
    assert len(enqueued_jobs) == 0


def test_livekit_webhook_duplicate_event_is_idempotent(client, monkeypatch):
    enqueued_jobs = []
    monkeypatch.setattr("app.services.recording_service._enqueue_ai_job", lambda _db, job_id: enqueued_jobs.append(job_id))
    client.app.dependency_overrides[get_storage_service] = lambda: mock_storage

    data = setup_meeting_fixture(client)
    meeting_id = data["meeting_id"]

    start_res = client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/auto/start",
        headers=auth_headers(data["host_token"]),
    ).json()

    from tests.conftest import TestingSessionLocal
    from app.models.recording import MeetingRecording
    from uuid import UUID

    db = TestingSessionLocal()
    rec = db.query(MeetingRecording).filter(MeetingRecording.id == UUID(start_res["id"])).first()
    rec.egress_id = "EG_TEST_DUPLICATE"
    db.commit()
    db.close()

    class MockFileInfo:
        filename = "meeting.mp4"
        content = b"sample video/audio"

    class MockEgressInfo:
        egress_id = "EG_TEST_DUPLICATE"
        status = "EGRESS_COMPLETE"
        error = None
        file_results = [MockFileInfo()]

    class MockWebhookEvent:
        event = "egress_ended"
        egress_info = MockEgressInfo()

    monkeypatch.setattr(
        "app.api.v1.recordings.verify_livekit_webhook",
        lambda _body, _auth: MockWebhookEvent()
    )

    # First webhook event: processed successfully
    r1 = client.post(
        "/api/v1/recordings/livekit-webhook",
        headers={"Authorization": "Bearer mock-livekit-token"},
        json={"event": "egress_ended"},
    )
    assert r1.status_code == 200
    assert r1.json()["status"] == "processed"
    assert len(enqueued_jobs) == 1

    # Second duplicate webhook event: ignored cleanly
    r2 = client.post(
        "/api/v1/recordings/livekit-webhook",
        headers={"Authorization": "Bearer mock-livekit-token"},
        json={"event": "egress_ended"},
    )
    client.app.dependency_overrides.pop(get_storage_service, None)

    assert r2.status_code == 200
    assert r2.json()["status"] == "already_processed"
    # Still only 1 job enqueued (no double dispatch)
    assert len(enqueued_jobs) == 1


def test_regression_sqlite_uuid_conversion(client):
    """Verify that querying entities with GUID TypeDecorator handles UUIDs, strings, and coercion cleanly."""
    from tests.conftest import TestingSessionLocal
    from app.models.document import Document
    import uuid

    db = TestingSessionLocal()
    try:
        doc = Document(
            public_id="reg_doc_001",
            company_id="comp_reg_1",
            title="Regression Test Document",
            file_name="regression.pdf",
            file_type="pdf",
            file_url="/docs/reg.pdf",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        assert isinstance(doc.id, uuid.UUID)

        # Query all documents
        queried = db.query(Document).filter(Document.company_id == "comp_reg_1").all()
        assert len(queried) == 1
        assert isinstance(queried[0].id, uuid.UUID)
        assert queried[0].id == doc.id
    finally:
        db.close()


def test_livekit_webhook_rejects_invalid_signature(client):
    response = client.post(
        "/api/v1/recordings/livekit-webhook",
        headers={"Authorization": "Invalid-Bad-Signature"},
        json={"event": "egress_ended"},
    )
    assert response.status_code == 401
    assert "Invalid webhook signature" in response.json()["detail"]
