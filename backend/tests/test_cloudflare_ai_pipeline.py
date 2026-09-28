from uuid import uuid4

from app.core.config import settings
from app.models.ai_job import AIJob
from app.models.decision import Decision
from app.models.meeting import Meeting
from app.models.meeting_summary import MeetingSummary
from app.models.recording import MeetingRecording
from app.models.task import Task
from app.models.topic import Topic
from app.models.transcript import TranscriptSegment


def _register_and_login(client):
    email = f"cf-ai-{uuid4()}@example.com"
    password = "Password123!"
    register = client.post(
        "/api/v1/auth/register",
        json={"full_name": "Cloudflare AI Tester", "email": email, "password": password},
    )
    assert register.status_code == 201, register.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return register.json(), {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_project_with_meetings(client, headers):
    company = client.post("/api/v1/companies", json={"name": "Cloudflare AI Test Org"}, headers=headers)
    assert company.status_code == 201, company.text
    company_id = company.json()["public_id"]

    project = client.post(
        f"/api/v1/companies/{company_id}/projects",
        json={"name": "Cross Meeting AI Pipeline"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["public_id"]

    meetings = []
    for title in ("Cloudflare Worker Planning", "Cloudflare Worker Follow-up"):
        response = client.post(
            f"/api/v1/companies/{company_id}/meetings",
            json={"title": title, "project_id": project_id},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        meetings.append(response.json()["public_id"])
    return company_id, project_id, meetings


def _create_recording_job(db, *, meeting_id, company_id, user_id, index):
    recording = MeetingRecording(
        meeting_id=meeting_id,
        company_id=company_id,
        uploaded_by_user_id=user_id,
        storage_backend="supabase",
        storage_bucket="meeting-recordings",
        storage_path=f"test/{meeting_id}/recording-{index}.webm",
        original_filename=f"recording-{index}.webm",
        file_type="video/webm",
        file_size_bytes=1024,
        duration_seconds=90,
        processing_status="QUEUED",
    )
    db.add(recording)
    db.flush()

    job = AIJob(
        public_id=f"AIJ-CF-{index}",
        meeting_id=meeting_id,
        recording_id=str(recording.id),
        company_id=company_id,
        requested_by_user_id=user_id,
        status="QUEUED",
        provider="cloudflare-workers-ai",
    )
    db.add(job)
    db.commit()
    return job.public_id


def test_cloudflare_ai_callback_persists_analysis_and_cross_meeting_timeline(client, setup_db, monkeypatch):
    from tests.conftest import TestingSessionLocal

    monkeypatch.setattr(settings, "CLOUDFLARE_AI_CALLBACK_SECRET", "test-callback-secret")
    user, headers = _register_and_login(client)
    company_id, project_id, meeting_ids = _create_project_with_meetings(client, headers)

    db = TestingSessionLocal()
    try:
        job_ids = [
            _create_recording_job(
                db,
                meeting_id=meeting_ids[0],
                company_id=company_id,
                user_id=user["public_id"],
                index=1,
            ),
            _create_recording_job(
                db,
                meeting_id=meeting_ids[1],
                company_id=company_id,
                user_id=user["public_id"],
                index=2,
            ),
        ]
    finally:
        db.close()

    callback_headers = {"x-meetvault-worker-secret": "test-callback-secret"}
    payloads = [
        {
            "provider": "cloudflare-workers-ai",
            "segments": [
                {
                    "start_time": 0,
                    "end_time": 12,
                    "speaker_label": "HOST",
                    "text": "We decided to move meeting analysis to Cloudflare Queues for background processing.",
                },
                {
                    "start_time": 12,
                    "end_time": 28,
                    "speaker_label": "ENGINEER",
                    "text": "I will finish the Render environment checklist by Friday.",
                },
            ],
        },
        {
            "provider": "cloudflare-workers-ai",
            "segments": [
                {
                    "start_time": 0,
                    "end_time": 16,
                    "speaker_label": "HOST",
                    "text": "The concern is queue retries if the worker fails during transcription.",
                },
                {
                    "start_time": 16,
                    "end_time": 34,
                    "speaker_label": "ENGINEER",
                    "text": "We agreed to monitor ai_jobs status and send failed jobs back for review.",
                },
            ],
        },
    ]

    for job_id, payload in zip(job_ids, payloads):
        response = client.post(
            f"/api/v1/ai-jobs/{job_id}/cloudflare/result",
            json=payload,
            headers=callback_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["ok"] is True

    db = TestingSessionLocal()
    try:
        assert db.query(AIJob).filter(AIJob.status == "COMPLETED").count() == 2
        assert db.query(TranscriptSegment).count() == 4
        assert db.query(MeetingSummary).count() == 2
        assert db.query(Topic).count() >= 2
        assert db.query(Decision).count() >= 1
        assert db.query(Task).count() >= 1
        assert db.query(Meeting).filter(Meeting.analysis_status == "completed").count() == 2
    finally:
        db.close()

    timeline = client.get(f"/api/v1/projects/{project_id}/timeline", headers=headers)
    assert timeline.status_code == 200, timeline.text
    body = timeline.json()
    assert body["project_id"] == project_id
    assert body["total_events"] >= 2
    assert len([event for event in body["timeline"] if event["event_type"] == "MEETING"]) == 2
