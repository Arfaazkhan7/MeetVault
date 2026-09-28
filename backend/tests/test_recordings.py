from app.services.storage_service import StoredObject, get_storage_service


class FakeStorageService:
    def __init__(self):
        self.objects = {}

    def upload_private_file(self, *, path: str, content: bytes, content_type: str) -> StoredObject:
        self.objects[path] = {"content": content, "content_type": content_type}
        return StoredObject(backend="supabase", bucket="test-recordings", path=path)

    def create_signed_url(self, *, path: str, expires_in_seconds: int) -> str:
        return f"https://storage.example.test/signed/{path}?expires={expires_in_seconds}"

    def download_private_file(self, *, path: str) -> bytes:
        return self.objects[path]["content"]


fake_storage = FakeStorageService()


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


def setup_recording_scenario(client):
    admin = register(client, "rec-admin@example.com", "Recording Admin")
    member = register(client, "rec-member@example.com", "Recording Member")
    outsider = register(client, "rec-outsider@example.com", "Recording Outsider")
    admin_token = login(client, "rec-admin@example.com")

    company = client.post(
        "/api/v1/companies",
        json={"name": "Recording Co"},
        headers=auth_headers(admin_token),
    ).json()
    company_id = company["public_id"]
    client.post(
        f"/api/v1/companies/{company_id}/members",
        json={"email": "rec-member@example.com", "role": "MEMBER"},
        headers=auth_headers(admin_token),
    )
    project = client.post(
        f"/api/v1/companies/{company_id}/projects",
        json={"name": "Recordings"},
        headers=auth_headers(admin_token),
    ).json()
    meeting = client.post(
        f"/api/v1/companies/{company_id}/meetings",
        json={"title": "Recording Meeting", "project_id": project["public_id"]},
        headers=auth_headers(admin_token),
    ).json()
    client.post(
        f"/api/v1/meetings/{meeting['public_id']}/participants",
        json={"user_public_id": member["public_id"], "role": "ATTENDEE"},
        headers=auth_headers(admin_token),
    )
    return {
        "admin": admin,
        "admin_token": admin_token,
        "member": member,
        "member_token": login(client, "rec-member@example.com"),
        "outsider": outsider,
        "outsider_token": login(client, "rec-outsider@example.com"),
        "meeting": meeting,
    }


def test_host_can_upload_recording_to_private_storage(client, monkeypatch):
    monkeypatch.setattr("app.services.recording_service._enqueue_ai_job", lambda _db, _job_id: None)
    client.app.dependency_overrides[get_storage_service] = lambda: fake_storage
    data = setup_recording_scenario(client)
    response = client.post(
        f"/api/v1/meetings/{data['meeting']['public_id']}/recordings",
        headers=auth_headers(data["admin_token"]),
        data={"duration_seconds": "42"},
        files={"file": ("meeting.mp4", b"video-bytes", "video/mp4")},
    )
    client.app.dependency_overrides.pop(get_storage_service, None)

    body = response.json()
    assert response.status_code == 201, response.text
    assert body["meeting_id"] == data["meeting"]["public_id"]
    assert body["company_id"] == data["meeting"]["company_id"]
    assert body["uploaded_by_user_id"] == data["admin"]["public_id"]
    assert body["storage_backend"] == "supabase"
    assert body["storage_bucket"] == "test-recordings"
    assert body["file_type"] == "video/mp4"
    assert body["file_size_bytes"] == len(b"video-bytes")
    assert body["duration_seconds"] == 42
    assert body["processing_status"] == "QUEUED"
    assert body["ai_job_id"].startswith("AIJ-")
    assert body["storage_path"] in fake_storage.objects

    jobs = client.get(
        f"/api/v1/meetings/{data['meeting']['public_id']}/ai-jobs",
        headers=auth_headers(data["admin_token"]),
    )
    assert jobs.status_code == 200
    assert jobs.json()[0]["status"] == "QUEUED"


def test_host_can_upload_low_bitrate_audio_webm_recording(client, monkeypatch):
    monkeypatch.setattr("app.services.recording_service._enqueue_ai_job", lambda _db, _job_id: None)
    client.app.dependency_overrides[get_storage_service] = lambda: fake_storage
    data = setup_recording_scenario(client)
    response = client.post(
        f"/api/v1/meetings/{data['meeting']['public_id']}/recordings",
        headers=auth_headers(data["admin_token"]),
        data={"duration_seconds": "3600"},
        files={"file": ("meeting-audio.webm", b"opus-audio-bytes", "audio/webm")},
    )
    client.app.dependency_overrides.pop(get_storage_service, None)

    body = response.json()
    assert response.status_code == 201, response.text
    assert body["file_type"] == "audio/webm"
    assert body["original_filename"] == "meeting-audio.webm"
    assert body["duration_seconds"] == 3600
    assert body["processing_status"] == "QUEUED"
    assert body["storage_path"] in fake_storage.objects


def test_non_host_cannot_upload_recording(client):
    client.app.dependency_overrides[get_storage_service] = lambda: fake_storage
    data = setup_recording_scenario(client)
    response = client.post(
        f"/api/v1/meetings/{data['meeting']['public_id']}/recordings",
        headers=auth_headers(data["member_token"]),
        files={"file": ("meeting.mp4", b"video-bytes", "video/mp4")},
    )
    client.app.dependency_overrides.pop(get_storage_service, None)
    assert response.status_code == 403


def test_rejects_unsupported_recording_file_type(client):
    client.app.dependency_overrides[get_storage_service] = lambda: fake_storage
    data = setup_recording_scenario(client)
    response = client.post(
        f"/api/v1/meetings/{data['meeting']['public_id']}/recordings",
        headers=auth_headers(data["admin_token"]),
        files={"file": ("notes.txt", b"not media", "text/plain")},
    )
    client.app.dependency_overrides.pop(get_storage_service, None)
    assert response.status_code == 400


def test_authorized_member_can_list_and_get_signed_recording_url(client):
    client.app.dependency_overrides[get_storage_service] = lambda: fake_storage
    data = setup_recording_scenario(client)
    upload = client.post(
        f"/api/v1/meetings/{data['meeting']['public_id']}/recordings",
        headers=auth_headers(data["admin_token"]),
        files={"file": ("meeting.webm", b"webm-bytes", "video/webm")},
    ).json()

    list_response = client.get(
        f"/api/v1/meetings/{data['meeting']['public_id']}/recordings",
        headers=auth_headers(data["member_token"]),
    )
    signed_response = client.post(
        f"/api/v1/meetings/{data['meeting']['public_id']}/recordings/{upload['id']}/signed-url",
        headers=auth_headers(data["member_token"]),
    )
    client.app.dependency_overrides.pop(get_storage_service, None)

    assert list_response.status_code == 200, list_response.text
    assert len(list_response.json()) == 1
    assert signed_response.status_code == 200, signed_response.text
    assert signed_response.json()["recording_id"] == upload["id"]
    assert signed_response.json()["url"].startswith("https://storage.example.test/signed/")


def test_unauthorized_user_cannot_access_recordings(client):
    client.app.dependency_overrides[get_storage_service] = lambda: fake_storage
    data = setup_recording_scenario(client)
    upload = client.post(
        f"/api/v1/meetings/{data['meeting']['public_id']}/recordings",
        headers=auth_headers(data["admin_token"]),
        files={"file": ("meeting.mp4", b"video-bytes", "video/mp4")},
    ).json()
    list_response = client.get(
        f"/api/v1/meetings/{data['meeting']['public_id']}/recordings",
        headers=auth_headers(data["outsider_token"]),
    )
    signed_response = client.post(
        f"/api/v1/meetings/{data['meeting']['public_id']}/recordings/{upload['id']}/signed-url",
        headers=auth_headers(data["outsider_token"]),
    )
    client.app.dependency_overrides.pop(get_storage_service, None)

    assert list_response.status_code == 403
    assert signed_response.status_code == 403


def test_host_can_update_processing_status_without_transcribing(client):
    client.app.dependency_overrides[get_storage_service] = lambda: fake_storage
    data = setup_recording_scenario(client)
    upload = client.post(
        f"/api/v1/meetings/{data['meeting']['public_id']}/recordings",
        headers=auth_headers(data["admin_token"]),
        files={"file": ("meeting.mp3", b"audio-bytes", "audio/mpeg")},
    ).json()
    response = client.patch(
        f"/api/v1/meetings/{data['meeting']['public_id']}/recordings/{upload['id']}/status",
        headers=auth_headers(data["admin_token"]),
        json={"processing_status": "QUEUED"},
    )
    client.app.dependency_overrides.pop(get_storage_service, None)

    assert response.status_code == 200, response.text
    assert response.json()["processing_status"] == "QUEUED"
