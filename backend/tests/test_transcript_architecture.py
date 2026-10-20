"""
Automated test suite for MeetVault multi-participant, speaker-attributed transcript architecture.

Covers:
1. One meeting with multiple participants (registered users and guests).
2. Multiple transcript segments from the same participant.
3. Different participants speaking in the same meeting.
4. Unknown and unconfirmed speaker attribution handling.
5. Duplicate segment prevention / idempotency.
6. Speaker-specific filtering and cross-meeting isolation.
7. Unauthorized user access rejection (403 Forbidden).
8. Invalid speaker ID validation (404 Not Found when speaker not in meeting).
9. Guest participant handling without fake user creation.
10. SpeakerMappingService participant validation (no blind reassignment).
11. Backward compatibility with existing/legacy transcript records.
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from app.models.company import Company, CompanyMember
from app.models.meeting import Meeting, MeetingParticipant
from app.models.transcript import TranscriptSegment
from app.models.user import User
from app.core.tokens import create_token
from app.services.speaker_mapping_service import SpeakerMappingService
from app.services.transcription_service import TranscriptionService
from tests.conftest import TestingSessionLocal


@pytest.fixture
def test_setup():
    """Setup company, owner, multiple attendees, and meetings."""
    db = TestingSessionLocal()
    try:
        # Company
        company = Company(public_id="comp-arch-1", name="Vault Corp", domain="vaultcorp.com")
        db.add(company)
        db.commit()

        # Users
        owner = User(
            public_id="usr-owner-101",
            email="owner@vaultcorp.com",
            full_name="Alice Owner",
            hashed_password="hash",
            account_type="company",
        )
        user_bob = User(
            public_id="usr-bob-102",
            email="bob@vaultcorp.com",
            full_name="Bob Engineer",
            hashed_password="hash",
            account_type="company",
        )
        user_carol = User(
            public_id="usr-carol-103",
            email="carol@vaultcorp.com",
            full_name="Carol Designer",
            hashed_password="hash",
            account_type="company",
        )
        user_outsider = User(
            public_id="usr-outsider-999",
            email="outsider@other.com",
            full_name="Dave Outsider",
            hashed_password="hash",
            account_type="personal",
        )
        db.add_all([owner, user_bob, user_carol, user_outsider])
        db.commit()

        # Company memberships
        db.add_all([
            CompanyMember(company_id=company.public_id, user_id=owner.public_id, role="COMPANY_ADMIN"),
            CompanyMember(company_id=company.public_id, user_id=user_bob.public_id, role="MEMBER"),
            CompanyMember(company_id=company.public_id, user_id=user_carol.public_id, role="MEMBER"),
        ])
        db.commit()

        # Meeting 1
        meeting = Meeting(
            public_id="mtg-arch-101",
            company_id=company.public_id,
            owner_id=owner.public_id,
            title="Q3 Product Strategy",
            meeting_type="SCHEDULED",
            status="COMPLETED",
            transcription_status="completed",
        )
        # Meeting 2 (separate meeting for cross-meeting isolation test)
        meeting_other = Meeting(
            public_id="mtg-arch-202",
            company_id=company.public_id,
            owner_id=owner.public_id,
            title="Private Executive Sync",
            meeting_type="SCHEDULED",
            status="COMPLETED",
            transcription_status="completed",
        )
        db.add_all([meeting, meeting_other])
        db.commit()

        # Participants in Meeting 1: Owner, Bob, Carol
        part_owner = MeetingParticipant(
            meeting_id=meeting.public_id,
            user_id=owner.public_id,
            role="HOST",
            status="JOINED",
            livekit_identity=owner.public_id,
            identity_mapping_status="verified",
            is_guest=False,
            display_name=owner.full_name,
        )
        part_bob = MeetingParticipant(
            meeting_id=meeting.public_id,
            user_id=user_bob.public_id,
            role="ATTENDEE",
            status="JOINED",
            livekit_identity=user_bob.public_id,
            identity_mapping_status="verified",
            is_guest=False,
            display_name=user_bob.full_name,
        )
        part_carol = MeetingParticipant(
            meeting_id=meeting.public_id,
            user_id=user_carol.public_id,
            role="ATTENDEE",
            status="JOINED",
            livekit_identity=user_carol.public_id,
            identity_mapping_status="verified",
            is_guest=False,
            display_name=user_carol.full_name,
        )
        db.add_all([part_owner, part_bob, part_carol])
        db.commit()
        db.refresh(part_owner)
        db.refresh(part_bob)
        db.refresh(part_carol)

        tokens = {
            "owner": create_token(subject=owner.public_id, token_type="access"),
            "bob": create_token(subject=user_bob.public_id, token_type="access"),
            "carol": create_token(subject=user_carol.public_id, token_type="access"),
            "outsider": create_token(subject=user_outsider.public_id, token_type="access"),
        }

        yield {
            "company": company,
            "owner": owner,
            "bob": user_bob,
            "carol": user_carol,
            "outsider": user_outsider,
            "meeting": meeting,
            "meeting_other": meeting_other,
            "part_owner": part_owner,
            "part_bob": part_bob,
            "part_carol": part_carol,
            "tokens": tokens,
        }
    finally:
        db.close()


def test_one_meeting_multiple_participants(client: TestClient, test_setup):
    """Verify meeting has multiple participants with correct identity mapping and livekit identity."""
    meeting_id = test_setup["meeting"].public_id
    token = test_setup["tokens"]["owner"]

    resp = client.get(
        f"/api/v1/meetings/{meeting_id}/participants",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    participants = resp.json()
    assert len(participants) == 3

    identities = {p["user_public_id"]: p for p in participants}
    assert test_setup["owner"].public_id in identities
    assert test_setup["bob"].public_id in identities
    assert test_setup["carol"].public_id in identities

    bob_part = identities[test_setup["bob"].public_id]
    assert bob_part["role"] == "ATTENDEE"
    assert bob_part["is_guest"] is False
    assert bob_part["identity_mapping_status"] == "verified"
    assert bob_part["livekit_identity"] == test_setup["bob"].public_id


def test_multiple_participants_speaking_and_filtering(client: TestClient, test_setup):
    """
    Verify:
    1. Multiple transcript segments from the same participant.
    2. Different participants speaking in the same meeting.
    3. Filtering by speaker_user_id and dedicated speaker endpoint.
    """
    db = TestingSessionLocal()
    meeting = test_setup["meeting"]
    owner = test_setup["owner"]
    bob = test_setup["bob"]
    carol = test_setup["carol"]
    part_owner = test_setup["part_owner"]
    part_bob = test_setup["part_bob"]
    part_carol = test_setup["part_carol"]

    # Add 4 segments: Owner speaks twice, Bob speaks once, Carol speaks once
    seg1 = TranscriptSegment(
        id=str(uuid.uuid4()),
        meeting_id=meeting.public_id,
        user_id=owner.public_id,
        speaker_user_id=owner.public_id,
        participant_id=part_owner.id,
        speaker_label="SPEAKER_00",
        attribution_status="confirmed",
        start_time=0.0,
        end_time=4.5,
        text="Welcome everyone to our Q3 strategy meeting.",
        confidence=0.98,
        language="en",
    )
    seg2 = TranscriptSegment(
        id=str(uuid.uuid4()),
        meeting_id=meeting.public_id,
        user_id=bob.public_id,
        speaker_user_id=bob.public_id,
        participant_id=part_bob.id,
        speaker_label="SPEAKER_01",
        attribution_status="confirmed",
        start_time=5.0,
        end_time=9.2,
        text="On the backend side, database migration is planned.",
        confidence=0.95,
        language="en",
    )
    seg3 = TranscriptSegment(
        id=str(uuid.uuid4()),
        meeting_id=meeting.public_id,
        user_id=carol.public_id,
        speaker_user_id=carol.public_id,
        participant_id=part_carol.id,
        speaker_label="SPEAKER_02",
        attribution_status="confirmed",
        start_time=10.0,
        end_time=14.0,
        text="Design tokens and UI components are ready.",
        confidence=0.96,
        language="en",
    )
    seg4 = TranscriptSegment(
        id=str(uuid.uuid4()),
        meeting_id=meeting.public_id,
        user_id=owner.public_id,
        speaker_user_id=owner.public_id,
        participant_id=part_owner.id,
        speaker_label="SPEAKER_00",
        attribution_status="confirmed",
        start_time=15.0,
        end_time=18.5,
        text="Excellent. Let's make sure we preserve zero data loss.",
        confidence=0.99,
        language="en",
    )
    db.add_all([seg1, seg2, seg3, seg4])
    db.commit()
    db.close()

    # 1. Fetch full transcript
    token_bob = test_setup["tokens"]["bob"]
    resp_full = client.get(
        f"/api/v1/transcripts/meetings/{meeting.public_id}",
        headers={"Authorization": f"Bearer {token_bob}"},
    )
    assert resp_full.status_code == 200
    data_full = resp_full.json()
    assert len(data_full["segments"]) == 4

    # 2. Filter by speaker_user_id via query parameter
    resp_owner = client.get(
        f"/api/v1/transcripts/meetings/{meeting.public_id}?speaker_user_id={owner.public_id}",
        headers={"Authorization": f"Bearer {token_bob}"},
    )
    assert resp_owner.status_code == 200
    owner_segs = resp_owner.json()["segments"]
    assert len(owner_segs) == 2
    assert all(s["speaker_user_id"] == owner.public_id for s in owner_segs)
    assert owner_segs[0]["text"] == "Welcome everyone to our Q3 strategy meeting."
    assert owner_segs[1]["text"] == "Excellent. Let's make sure we preserve zero data loss."

    # 3. Filter by Bob via dedicated speaker endpoint
    resp_bob = client.get(
        f"/api/v1/transcripts/meetings/{meeting.public_id}/speakers/{bob.public_id}",
        headers={"Authorization": f"Bearer {token_bob}"},
    )
    assert resp_bob.status_code == 200
    bob_segs = resp_bob.json()["segments"]
    assert len(bob_segs) == 1
    assert bob_segs[0]["speaker_user_id"] == bob.public_id
    assert "backend side" in bob_segs[0]["text"]

    # 4. Filter by Carol via query parameter
    resp_carol = client.get(
        f"/api/v1/transcripts/meetings/{meeting.public_id}?speaker_user_id={carol.public_id}",
        headers={"Authorization": f"Bearer {token_bob}"},
    )
    assert resp_carol.status_code == 200
    carol_segs = resp_carol.json()["segments"]
    assert len(carol_segs) == 1
    assert carol_segs[0]["speaker_user_id"] == carol.public_id


def test_unknown_and_unconfirmed_speaker_attribution(client: TestClient, test_setup):
    """Verify segments with unmapped speakers retain unknown/unconfirmed status and nullable speaker_user_id."""
    db = TestingSessionLocal()
    meeting = test_setup["meeting"]

    seg_unconfirmed = TranscriptSegment(
        id=str(uuid.uuid4()),
        meeting_id=meeting.public_id,
        user_id=None,
        speaker_user_id=None,
        participant_id=None,
        speaker_label="SPEAKER_99",
        attribution_status="unconfirmed",
        start_time=20.0,
        end_time=23.0,
        text="Could someone mute their microphone please?",
        confidence=0.88,
    )
    db.add(seg_unconfirmed)
    db.commit()
    db.close()

    token = test_setup["tokens"]["owner"]
    resp = client.get(
        f"/api/v1/transcripts/meetings/{meeting.public_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    segments = resp.json()["segments"]
    unconfirmed = next(s for s in segments if s["speaker_label"] == "SPEAKER_99")
    assert unconfirmed["speaker_user_id"] is None
    assert unconfirmed["participant_id"] is None
    assert unconfirmed["attribution_status"] in ("unconfirmed", "unknown")


def test_duplicate_segment_prevention_and_idempotency(test_setup):
    """Verify duplicate segment insertion is handled safely without duplicating transcript data."""
    db = TestingSessionLocal()
    meeting = test_setup["meeting"]
    owner = test_setup["owner"]
    part_owner = test_setup["part_owner"]

    stable_seg_id = f"{meeting.public_id}_seg_0001"

    seg1 = TranscriptSegment(
        id=stable_seg_id,
        meeting_id=meeting.public_id,
        user_id=owner.public_id,
        speaker_user_id=owner.public_id,
        participant_id=part_owner.id,
        speaker_label="SPEAKER_00",
        attribution_status="confirmed",
        start_time=1.0,
        end_time=3.0,
        text="First delivery.",
    )
    db.add(seg1)
    db.commit()

    # Re-inserting with the same primary key ID raises IntegrityError or is prevented
    seg_duplicate = TranscriptSegment(
        id=stable_seg_id,
        meeting_id=meeting.public_id,
        user_id=owner.public_id,
        speaker_user_id=owner.public_id,
        participant_id=part_owner.id,
        speaker_label="SPEAKER_00",
        attribution_status="confirmed",
        start_time=1.0,
        end_time=3.0,
        text="Duplicate delivery attempt.",
    )
    db.add(seg_duplicate)
    with pytest.raises(Exception):
        db.commit()
    db.rollback()

    # Verify only one segment exists with that ID
    count = db.query(TranscriptSegment).filter(TranscriptSegment.id == stable_seg_id).count()
    assert count == 1
    db.close()


def test_unauthorized_user_cannot_access_transcript(client: TestClient, test_setup):
    """Verify user not participating or affiliated with meeting cannot view transcript (403 Forbidden)."""
    meeting_id = test_setup["meeting"].public_id
    token_outsider = test_setup["tokens"]["outsider"]

    # Full transcript attempt
    resp = client.get(
        f"/api/v1/transcripts/meetings/{meeting_id}",
        headers={"Authorization": f"Bearer {token_outsider}"},
    )
    assert resp.status_code == 403
    assert any(m in resp.json()["detail"].lower() for m in ["not authorized", "not a member"])

    # Speaker-specific attempt
    resp_speaker = client.get(
        f"/api/v1/transcripts/meetings/{meeting_id}/speakers/{test_setup['owner'].public_id}",
        headers={"Authorization": f"Bearer {token_outsider}"},
    )
    assert resp_speaker.status_code == 403


def test_invalid_speaker_filtering_returns_404(client: TestClient, test_setup):
    """
    Verify cross-meeting isolation: querying a speaker who is not a participant
    in the requested meeting returns 404 Not Found.
    """
    meeting_id = test_setup["meeting"].public_id
    token_owner = test_setup["tokens"]["owner"]
    outsider_id = test_setup["outsider"].public_id

    # 1. Via query parameter
    resp_query = client.get(
        f"/api/v1/transcripts/meetings/{meeting_id}?speaker_user_id={outsider_id}",
        headers={"Authorization": f"Bearer {token_owner}"},
    )
    assert resp_query.status_code == 404
    assert "not an authorized participant" in resp_query.json()["detail"].lower()

    # 2. Via dedicated speaker endpoint
    resp_path = client.get(
        f"/api/v1/transcripts/meetings/{meeting_id}/speakers/{outsider_id}",
        headers={"Authorization": f"Bearer {token_owner}"},
    )
    assert resp_path.status_code == 404
    assert "not an authorized participant" in resp_path.json()["detail"].lower()


def test_guest_participant_handling_without_fake_user(client: TestClient, test_setup):
    """
    Verify guest participants can join, receive a LiveKit token and guest identity,
    without creating a fake record in the User table.
    """
    db = TestingSessionLocal()
    initial_user_count = db.query(User).count()
    db.close()

    meeting_id = test_setup["meeting"].public_id

    # Guest joins meeting
    resp = client.post(
        f"/api/v1/meetings/{meeting_id}/participants/guest",
        json={"display_name": "Dr. Sarah Guest"},
    )
    assert resp.status_code == 200
    guest_data = resp.json()
    participant_info = guest_data["participant"]
    assert participant_info["is_guest"] is True
    assert participant_info["display_name"] == "Dr. Sarah Guest"
    assert participant_info["user_public_id"] is None
    assert participant_info["livekit_identity"].startswith("guest:")
    assert "token" in guest_data

    # Check database: no new user was inserted into users table
    db = TestingSessionLocal()
    new_user_count = db.query(User).count()
    assert new_user_count == initial_user_count

    # Check participant in database
    guest_part = db.query(MeetingParticipant).filter(
        MeetingParticipant.id == participant_info["participant_id"]
    ).first()
    assert guest_part is not None
    assert guest_part.user_id is None
    assert guest_part.is_guest is True
    assert guest_part.identity_mapping_status == "guest"
    guest_part_id = guest_part.id

    # Guest produces a transcript segment
    guest_seg = TranscriptSegment(
        id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        user_id=None,
        speaker_user_id=None,
        participant_id=guest_part_id,
        speaker_label="SPEAKER_GUEST",
        attribution_status="verified_guest",
        start_time=30.0,
        end_time=35.0,
        text="Hello from the guest speaker.",
        confidence=0.97,
    )
    db.add(guest_seg)
    db.commit()
    db.close()

    # Query transcript filtered by participant_id
    token_owner = test_setup["tokens"]["owner"]
    resp_guest_seg = client.get(
        f"/api/v1/transcripts/meetings/{meeting_id}?participant_id={guest_part_id}",
        headers={"Authorization": f"Bearer {token_owner}"},
    )
    assert resp_guest_seg.status_code == 200
    segs = resp_guest_seg.json()["segments"]
    assert len(segs) == 1
    assert segs[0]["text"] == "Hello from the guest speaker."
    assert segs[0]["participant_id"] == str(guest_part_id)
    assert segs[0]["speaker_user_id"] is None
    assert segs[0]["attribution_status"] == "verified_guest"


def test_speaker_mapping_service_validates_membership(test_setup):
    """Verify SpeakerMappingService validates participant membership and rejects non-participants."""
    db = TestingSessionLocal()
    meeting = test_setup["meeting"]
    bob = test_setup["bob"]
    outsider = test_setup["outsider"]

    # Create unmapped segment
    seg = TranscriptSegment(
        id=str(uuid.uuid4()),
        meeting_id=meeting.public_id,
        user_id=None,
        speaker_user_id=None,
        speaker_label="SPEAKER_05",
        attribution_status="unconfirmed",
        start_time=40.0,
        end_time=45.0,
        text="Unmapped speech block.",
    )
    db.add(seg)
    db.commit()

    service = SpeakerMappingService()
    service.create_speaker_mappings(db, meeting, ["SPEAKER_05"])

    # 1. Attempting to map to outsider (not a participant) must raise ValueError
    with pytest.raises(ValueError, match="not an authorized participant"):
        service.update_speaker_mapping(
            db=db,
            meeting_id=meeting.public_id,
            speaker_label="SPEAKER_05",
            user_id=outsider.public_id,
        )

    # 2. Mapping to valid participant Bob succeeds and sets speaker_user_id, participant_id, and attribution_status
    mapping = service.update_speaker_mapping(
        db=db,
        meeting_id=meeting.public_id,
        speaker_label="SPEAKER_05",
        user_id=bob.public_id,
        is_confirmed=True,
    )
    assert mapping.user_id == bob.public_id
    assert mapping.is_confirmed is True

    db.refresh(seg)
    assert seg.speaker_user_id == bob.public_id
    assert seg.user_id == bob.public_id
    assert seg.attribution_status == "confirmed"
    assert seg.participant_id == test_setup["part_bob"].id
    db.close()


def test_empty_transcript_state_returns_200_with_empty_list(client: TestClient, test_setup):
    """Verify meeting without transcript returns 200 with empty segments list rather than error."""
    meeting_other = test_setup["meeting_other"]
    token_owner = test_setup["tokens"]["owner"]

    resp = client.get(
        f"/api/v1/transcripts/meetings/{meeting_other.public_id}",
        headers={"Authorization": f"Bearer {token_owner}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["meeting_id"] == meeting_other.public_id
    assert data["segments"] == []


def test_legacy_transcript_record_backward_compatibility(client: TestClient, test_setup):
    """
    Verify legacy records that only have user_id (and speaker_user_id populated via fallback)
    query cleanly and serialize properly through the API.
    """
    db = TestingSessionLocal()
    meeting = test_setup["meeting"]
    owner = test_setup["owner"]

    # Simulate legacy record: only user_id was set, speaker_user_id was set to user_id, participant_id is None
    legacy_seg = TranscriptSegment(
        id=str(uuid.uuid4()),
        meeting_id=meeting.public_id,
        user_id=owner.public_id,
        speaker_user_id=owner.public_id,
        participant_id=None,
        speaker_label="SPEAKER_00",
        attribution_status="legacy",
        start_time=50.0,
        end_time=55.0,
        text="Legacy transcript segment text.",
        confidence=0.91,
    )
    db.add(legacy_seg)
    db.commit()
    db.close()

    token = test_setup["tokens"]["owner"]
    resp = client.get(
        f"/api/v1/transcripts/meetings/{meeting.public_id}?speaker_user_id={owner.public_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    segs = resp.json()["segments"]
    legacy_match = next((s for s in segs if s["text"] == "Legacy transcript segment text."), None)
    assert legacy_match is not None
    assert legacy_match["speaker_user_id"] == owner.public_id
    assert legacy_match["participant_id"] is None
