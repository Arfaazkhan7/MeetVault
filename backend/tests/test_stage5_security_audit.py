"""
Stage 5 Security and Consistency Audit Test Suite.

Validates:
1. Authentication enforcement (401 for missing/invalid bearer token).
2. Authorization and meeting membership enforcement on listing and status endpoints (403 for unauthorized users).
3. Cross-company and cross-meeting isolation when guessing meeting IDs.
4. Participant impersonation prevention on live audio upload (403 when caller != participant.user_id).
5. Guest participant audio submission prevention (403 when trying to submit as guest).
6. Cross-meeting participant ID rejection (404 when participant ID belongs to another meeting).
7. Cross-meeting speaker/participant filtering isolation (404 when filter target is not in meeting).
8. Upload payload limits: 25MB limit on live audio chunks (413) and 500MB limit on whole recordings (413).
9. Duration bounds: rejection of chunks exceeding 300 seconds (400) even when end_offset is omitted.
10. Host-only privilege enforcement on whole-meeting recording upload and transcript deletion (403 for non-hosts).
11. Authorized meeting participants can successfully submit audio, check status, and retrieve transcripts.
"""
import io
import wave
import uuid
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.models.company import Company, CompanyMember
from app.models.meeting import Meeting, MeetingParticipant
from app.models.transcript import TranscriptSegment
from app.models.user import User
from app.core.tokens import create_token
from app.services.transcription_service import TranscriptionService
from tests.conftest import TestingSessionLocal


def _create_wav(duration_sec: float = 1.0, sample_rate: int = 16000) -> bytes:
    """Generate minimal valid PCM WAV bytes."""
    num_frames = int(duration_sec * sample_rate)
    pcm = b"\x00\x00" * num_frames
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


@pytest.fixture
def sec_setup():
    """Setup multi-tenant companies, users, meetings and participants."""
    db = TestingSessionLocal()
    try:
        # Company A
        comp_a = Company(public_id="comp-sec-a", name="Security Corp A", workspace_code="SEC-A")
        # Company B
        comp_b = Company(public_id="comp-sec-b", name="Security Corp B", workspace_code="SEC-B")
        db.add_all([comp_a, comp_b])
        db.flush()

        # Users
        host_a = User(public_id="usr-host-a", email="hosta@seca.com", full_name="Host A", hashed_password="h", account_type="company")
        member_a = User(public_id="usr-member-a", email="membera@seca.com", full_name="Member A", hashed_password="h", account_type="company")
        non_part_a = User(public_id="usr-nonpart-a", email="nonparta@seca.com", full_name="NonPart A", hashed_password="h", account_type="company")
        user_b = User(public_id="usr-user-b", email="userb@secb.com", full_name="User B", hashed_password="h", account_type="company")
        personal_owner = User(public_id="usr-pers-owner", email="pers@owner.com", full_name="Pers Owner", hashed_password="h", account_type="personal")
        personal_outsider = User(public_id="usr-pers-out", email="pers@out.com", full_name="Pers Out", hashed_password="h", account_type="personal")
        db.add_all([host_a, member_a, non_part_a, user_b, personal_owner, personal_outsider])
        db.flush()

        # Memberships
        db.add_all([
            CompanyMember(company_id=comp_a.public_id, user_id=host_a.public_id, role="COMPANY_ADMIN"),
            CompanyMember(company_id=comp_a.public_id, user_id=member_a.public_id, role="MEMBER"),
            CompanyMember(company_id=comp_a.public_id, user_id=non_part_a.public_id, role="MEMBER"),
            CompanyMember(company_id=comp_b.public_id, user_id=user_b.public_id, role="MEMBER"),
        ])
        db.flush()

        # Workspace Meeting A1
        mtg_a1 = Meeting(
            public_id="mtg-sec-a1",
            company_id=comp_a.public_id,
            owner_id=host_a.public_id,
            title="Workspace Meeting A1",
            meeting_type="WORKSPACE",
            status="LIVE",
            transcription_status="pending",
        )
        # Workspace Meeting B1
        mtg_b1 = Meeting(
            public_id="mtg-sec-b1",
            company_id=comp_b.public_id,
            owner_id=user_b.public_id,
            title="Workspace Meeting B1",
            meeting_type="WORKSPACE",
            status="LIVE",
            transcription_status="pending",
        )
        # Personal Meeting P1
        mtg_p1 = Meeting(
            public_id="mtg-sec-p1",
            company_id=None,
            owner_id=personal_owner.public_id,
            title="Personal Confidential Meeting",
            meeting_type="PERSONAL",
            status="COMPLETED",
            transcription_status="completed",
        )
        db.add_all([mtg_a1, mtg_b1, mtg_p1])
        db.flush()

        # Participants in Meeting A1
        part_host_a = MeetingParticipant(
            id=str(uuid.uuid4()),
            meeting_id=mtg_a1.public_id,
            user_id=host_a.public_id,
            role="HOST",
            status="JOINED",
            display_name="Host A",
            is_guest=False,
        )
        part_member_a = MeetingParticipant(
            id=str(uuid.uuid4()),
            meeting_id=mtg_a1.public_id,
            user_id=member_a.public_id,
            role="ATTENDEE",
            status="JOINED",
            display_name="Member A",
            is_guest=False,
        )
        guest_a = MeetingParticipant(
            id=str(uuid.uuid4()),
            meeting_id=mtg_a1.public_id,
            user_id=None,
            role="ATTENDEE",
            status="JOINED",
            display_name="Guest A",
            is_guest=True,
            identity_mapping_status="guest",
        )
        # Participant in Meeting B1
        part_user_b = MeetingParticipant(
            id=str(uuid.uuid4()),
            meeting_id=mtg_b1.public_id,
            user_id=user_b.public_id,
            role="HOST",
            status="JOINED",
            display_name="User B",
            is_guest=False,
        )
        db.add_all([part_host_a, part_member_a, guest_a, part_user_b])

        # Transcript segment in Personal Meeting P1
        seg_p1 = TranscriptSegment(
            id=str(uuid.uuid4()),
            meeting_id=mtg_p1.public_id,
            speaker_label="SPEAKER_00",
            user_id=personal_owner.public_id,
            speaker_user_id=personal_owner.public_id,
            start_time=0.0,
            end_time=3.0,
            text="Private personal discussion",
        )
        db.add(seg_p1)
        db.commit()

        tokens = {
            "host_a": create_token(subject=host_a.public_id, token_type="access"),
            "member_a": create_token(subject=member_a.public_id, token_type="access"),
            "non_part_a": create_token(subject=non_part_a.public_id, token_type="access"),
            "user_b": create_token(subject=user_b.public_id, token_type="access"),
            "personal_owner": create_token(subject=personal_owner.public_id, token_type="access"),
            "personal_outsider": create_token(subject=personal_outsider.public_id, token_type="access"),
        }

        yield {
            "mtg_a1": mtg_a1,
            "mtg_b1": mtg_b1,
            "mtg_p1": mtg_p1,
            "part_host_a": part_host_a,
            "part_member_a": part_member_a,
            "guest_a": guest_a,
            "part_user_b": part_user_b,
            "tokens": tokens,
        }
    finally:
        db.close()


def test_unauthenticated_transcript_requests_rejected_401(client: TestClient, sec_setup):
    """Endpoints require valid authentication bearer token."""
    mtg_id = sec_setup["mtg_a1"].public_id

    # Transcript listing
    r1 = client.get(f"/api/v1/transcripts/meetings/{mtg_id}")
    assert r1.status_code == 401

    # Transcript status
    r2 = client.get(f"/api/v1/transcripts/meetings/{mtg_id}/status")
    assert r2.status_code == 401

    # Audio stream
    part_id = sec_setup["part_host_a"].id
    wav = _create_wav(1.0)
    r3 = client.post(
        f"/api/v1/transcripts/meetings/{mtg_id}/participants/{part_id}/audio-stream",
        files={"file": ("c.wav", wav, "audio/wav")},
    )
    assert r3.status_code == 401


def test_unauthorized_user_cannot_read_personal_meeting_transcript_403(client: TestClient, sec_setup):
    """Outsider cannot read personal meeting transcript or status (403 Forbidden)."""
    mtg_p1 = sec_setup["mtg_p1"].public_id
    token_out = sec_setup["tokens"]["personal_outsider"]

    r_trans = client.get(
        f"/api/v1/transcripts/meetings/{mtg_p1}",
        headers={"Authorization": f"Bearer {token_out}"},
    )
    assert r_trans.status_code == 403
    assert "not authorized" in r_trans.json()["detail"].lower()

    r_stat = client.get(
        f"/api/v1/transcripts/meetings/{mtg_p1}/status",
        headers={"Authorization": f"Bearer {token_out}"},
    )
    assert r_stat.status_code == 403


def test_cross_company_transcript_access_blocked_403(client: TestClient, sec_setup):
    """User from Company B cannot access Company A's meeting transcript or status."""
    mtg_a = sec_setup["mtg_a1"].public_id
    token_b = sec_setup["tokens"]["user_b"]

    # Listing
    r_list = client.get(
        f"/api/v1/transcripts/meetings/{mtg_a}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r_list.status_code == 403
    assert "not a member of this company" in r_list.json()["detail"].lower()

    # Status
    r_stat = client.get(
        f"/api/v1/transcripts/meetings/{mtg_a}/status",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r_stat.status_code == 403
    assert "not a member of this company" in r_stat.json()["detail"].lower()


def test_guessing_nonexistent_meeting_id_returns_404(client: TestClient, sec_setup):
    """Guessing unknown meeting ID returns 404 without leaking internal state."""
    token = sec_setup["tokens"]["host_a"]
    r = client.get(
        "/api/v1/transcripts/meetings/non-existent-random-uuid-999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404
    assert "meeting not found" in r.json()["detail"].lower()


def test_participant_spoofing_prevented_403(client: TestClient, sec_setup):
    """User A cannot upload audio stream impersonating User B's participant record."""
    mtg_a = sec_setup["mtg_a1"].public_id
    part_member_a_id = sec_setup["part_member_a"].id  # belongs to member_a
    token_host = sec_setup["tokens"]["host_a"]         # caller is host_a
    wav = _create_wav(1.0)

    resp = client.post(
        f"/api/v1/transcripts/meetings/{mtg_a}/participants/{part_member_a_id}/audio-stream",
        headers={"Authorization": f"Bearer {token_host}"},
        files={"file": ("c.wav", wav, "audio/wav")},
        data={"start_offset": 0.0},
    )
    assert resp.status_code == 403
    assert "caller identity does not match participant" in resp.json()["detail"].lower()


def test_guest_participant_audio_submission_prevented_403(client: TestClient, sec_setup):
    """Authenticated user cannot forge audio on behalf of a guest participant (403 Forbidden)."""
    mtg_a = sec_setup["mtg_a1"].public_id
    guest_id = sec_setup["guest_a"].id
    token_host = sec_setup["tokens"]["host_a"]
    wav = _create_wav(1.0)

    resp = client.post(
        f"/api/v1/transcripts/meetings/{mtg_a}/participants/{guest_id}/audio-stream",
        headers={"Authorization": f"Bearer {token_host}"},
        files={"file": ("c.wav", wav, "audio/wav")},
        data={"start_offset": 0.0},
    )
    assert resp.status_code == 403
    assert "caller identity does not match participant" in resp.json()["detail"].lower()


def test_cross_meeting_participant_id_returns_404(client: TestClient, sec_setup):
    """Participant ID from Meeting B cannot be used in Meeting A endpoint (404 Not Found)."""
    mtg_a = sec_setup["mtg_a1"].public_id
    part_b_id = sec_setup["part_user_b"].id
    token_host = sec_setup["tokens"]["host_a"]
    wav = _create_wav(1.0)

    resp = client.post(
        f"/api/v1/transcripts/meetings/{mtg_a}/participants/{part_b_id}/audio-stream",
        headers={"Authorization": f"Bearer {token_host}"},
        files={"file": ("c.wav", wav, "audio/wav")},
        data={"start_offset": 0.0},
    )
    assert resp.status_code == 404
    assert "not found in meeting" in resp.json()["detail"].lower()


def test_cross_meeting_speaker_filtering_returns_404(client: TestClient, sec_setup):
    """Querying transcripts filtered by a speaker from another company/meeting returns 404."""
    mtg_a = sec_setup["mtg_a1"].public_id
    token_host = sec_setup["tokens"]["host_a"]

    # Filter with user_b who is not in Meeting A
    resp = client.get(
        f"/api/v1/transcripts/meetings/{mtg_a}?speaker_user_id=usr-user-b",
        headers={"Authorization": f"Bearer {token_host}"},
    )
    assert resp.status_code == 404
    assert "not an authorized participant" in resp.json()["detail"].lower()


def test_cross_meeting_participant_filtering_returns_404(client: TestClient, sec_setup):
    """Querying transcripts filtered by a participant_id from another meeting returns 404."""
    mtg_a = sec_setup["mtg_a1"].public_id
    part_b_id = sec_setup["part_user_b"].id
    token_host = sec_setup["tokens"]["host_a"]

    resp = client.get(
        f"/api/v1/transcripts/meetings/{mtg_a}?participant_id={part_b_id}",
        headers={"Authorization": f"Bearer {token_host}"},
    )
    assert resp.status_code == 404
    assert "does not belong to meeting" in resp.json()["detail"].lower()


def test_audio_chunk_payload_exceeding_25mb_rejected_413(client: TestClient, sec_setup):
    """Audio chunk upload exceeding 25MB is rejected with 413 Payload Too Large."""
    mtg_a = sec_setup["mtg_a1"].public_id
    part_id = sec_setup["part_host_a"].id
    token_host = sec_setup["tokens"]["host_a"]

    # Generate dummy oversized payload > 25MB (25MB + 1024 bytes)
    oversized_bytes = b"RIFF" + (b"\x00" * (25 * 1024 * 1024 + 1024))

    resp = client.post(
        f"/api/v1/transcripts/meetings/{mtg_a}/participants/{part_id}/audio-stream",
        headers={"Authorization": f"Bearer {token_host}"},
        files={"file": ("chunk_huge.wav", oversized_bytes, "audio/wav")},
        data={"start_offset": 0.0},
    )
    assert resp.status_code == 413
    assert "exceeds maximum allowed size" in resp.json()["detail"].lower()


def test_audio_chunk_duration_exceeding_300s_rejected_400(client: TestClient, sec_setup):
    """Audio chunk with duration > 300s is rejected even if end_offset form field is omitted."""
    mtg_a = sec_setup["mtg_a1"].public_id
    part_id = sec_setup["part_host_a"].id
    token_host = sec_setup["tokens"]["host_a"]

    # 305 seconds of 8000Hz mono audio = ~4.8MB
    long_wav = _create_wav(duration_sec=305.0, sample_rate=8000)

    resp = client.post(
        f"/api/v1/transcripts/meetings/{mtg_a}/participants/{part_id}/audio-stream",
        headers={"Authorization": f"Bearer {token_host}"},
        files={"file": ("chunk_long.wav", long_wav, "audio/wav")},
        data={"start_offset": 0.0},  # end_offset intentionally omitted
    )
    assert resp.status_code == 400
    assert "exceeds maximum allowed limit of 300 seconds" in resp.json()["detail"].lower()


def test_non_host_cannot_upload_whole_meeting_recording_403(client: TestClient, sec_setup):
    """Non-host participant cannot upload full meeting recording (403 Forbidden)."""
    mtg_a = sec_setup["mtg_a1"].public_id
    token_member = sec_setup["tokens"]["member_a"]  # attendee, not host
    wav = _create_wav(2.0)

    resp = client.post(
        f"/api/v1/transcripts/meetings/{mtg_a}/upload",
        headers={"Authorization": f"Bearer {token_member}"},
        files={"file": ("rec.wav", wav, "audio/wav")},
    )
    assert resp.status_code == 403
    assert "requires meeting host privileges" in resp.json()["detail"].lower()


def test_non_host_cannot_delete_transcripts_403(client: TestClient, sec_setup):
    """Non-host participant cannot delete transcript segments (403 Forbidden)."""
    mtg_a = sec_setup["mtg_a1"].public_id
    token_member = sec_setup["tokens"]["member_a"]

    resp = client.delete(
        f"/api/v1/transcripts/meetings/{mtg_a}",
        headers={"Authorization": f"Bearer {token_member}"},
    )
    assert resp.status_code == 403
    assert "requires meeting host privileges" in resp.json()["detail"].lower()


def test_oversized_recording_upload_rejected_413(client: TestClient, sec_setup):
    """Whole recording upload exceeding MAX_RECORDING_UPLOAD_BYTES is rejected with 413."""
    from app.core.config import settings

    mtg_a = sec_setup["mtg_a1"].public_id
    token_host = sec_setup["tokens"]["host_a"]

    # Temporarily lower MAX_RECORDING_UPLOAD_BYTES for test
    original_max = settings.MAX_RECORDING_UPLOAD_BYTES
    settings.MAX_RECORDING_UPLOAD_BYTES = 1024  # 1 KB

    try:
        wav = _create_wav(1.0)  # ~32KB > 1KB
        resp = client.post(
            f"/api/v1/transcripts/meetings/{mtg_a}/upload",
            headers={"Authorization": f"Bearer {token_host}"},
            files={"file": ("rec_large.wav", wav, "audio/wav")},
        )
        assert resp.status_code == 413
        assert "exceeds maximum allowed size" in resp.json()["detail"].lower()
    finally:
        settings.MAX_RECORDING_UPLOAD_BYTES = original_max


def test_empty_recording_upload_rejected_400(client: TestClient, sec_setup):
    """Empty (0-byte) recording upload is rejected with 400 Bad Request."""
    mtg_a = sec_setup["mtg_a1"].public_id
    token_host = sec_setup["tokens"]["host_a"]

    resp = client.post(
        f"/api/v1/transcripts/meetings/{mtg_a}/upload",
        headers={"Authorization": f"Bearer {token_host}"},
        files={"file": ("empty.wav", b"", "audio/wav")},
    )
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()


def test_authorized_participant_can_stream_and_read_transcripts_200(client: TestClient, sec_setup):
    """Authorized participant can submit live audio chunks and retrieve transcript segments."""
    mtg_a = sec_setup["mtg_a1"].public_id
    part_host = sec_setup["part_host_a"]
    token_host = sec_setup["tokens"]["host_a"]
    wav = _create_wav(2.0)

    mock_whisper = {
        "text": "Hello world from host.",
        "segments": [{"start_time": 0.0, "end_time": 1.8, "text": "Hello world from host."}],
        "language": "en",
    }

    with patch("app.services.transcription_service.LazyWhisperTranscriptionEngine.transcribe", return_value=mock_whisper):
        # 1. Post audio stream
        resp_post = client.post(
            f"/api/v1/transcripts/meetings/{mtg_a}/participants/{part_host.id}/audio-stream",
            headers={"Authorization": f"Bearer {token_host}"},
            files={"file": ("chunk_auth.wav", wav, "audio/wav")},
            data={"start_offset": 0.0, "sequence_number": 0, "chunk_id": f"{mtg_a}_auth_0"},
        )
        assert resp_post.status_code == 201
        data_post = resp_post.json()
        assert len(data_post) == 1
        assert data_post[0]["text"] == "Hello world from host."
        assert data_post[0]["speaker_user_id"] == "usr-host-a"

        # 2. Status shows partial / active
        resp_stat = client.get(
            f"/api/v1/transcripts/meetings/{mtg_a}/status",
            headers={"Authorization": f"Bearer {token_host}"},
        )
        assert resp_stat.status_code == 200
        assert resp_stat.json()["status"] == "partial"
        assert resp_stat.json()["segment_count"] == 1

        # 3. Read transcript listing
        resp_get = client.get(
            f"/api/v1/transcripts/meetings/{mtg_a}",
            headers={"Authorization": f"Bearer {token_host}"},
        )
        assert resp_get.status_code == 200
        data_get = resp_get.json()
        assert data_get["total_segments"] == 1
        assert data_get["segments"][0]["text"] == "Hello world from host."

        # 4. Host can delete transcript
        resp_del = client.delete(
            f"/api/v1/transcripts/meetings/{mtg_a}",
            headers={"Authorization": f"Bearer {token_host}"},
        )
        assert resp_del.status_code == 200
        assert "Deleted 1 transcript segments" in resp_del.json()["message"]
