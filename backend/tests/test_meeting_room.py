import json
from app.core.tokens import jwt

from app.core.config import settings


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


def setup_meeting(client):
    admin = register(client, "room-admin@example.com", "Room Admin")
    admin_token = login(client, "room-admin@example.com")
    company = client.post(
        "/api/v1/companies",
        json={"name": "Room Co"},
        headers=auth_headers(admin_token),
    ).json()
    company_id = company["public_id"]

    attendee = register(client, "room-member@example.com", "Room Member")
    second = register(client, "room-second@example.com", "Second Member")
    outsider = register(client, "room-outsider@example.com", "Outsider")
    for email in ["room-member@example.com", "room-second@example.com"]:
        client.post(
            f"/api/v1/companies/{company_id}/members",
            json={"email": email, "role": "MEMBER"},
            headers=auth_headers(admin_token),
        )

    project = client.post(
        f"/api/v1/companies/{company_id}/projects",
        json={"name": "Phase 6"},
        headers=auth_headers(admin_token),
    ).json()
    meeting = client.post(
        f"/api/v1/companies/{company_id}/meetings",
        json={"title": "Live Room", "project_id": project["public_id"]},
        headers=auth_headers(admin_token),
    ).json()

    for user in [attendee, second]:
        response = client.post(
            f"/api/v1/meetings/{meeting['public_id']}/participants",
            json={"user_public_id": user["public_id"], "role": "ATTENDEE"},
            headers=auth_headers(admin_token),
        )
        assert response.status_code == 201, response.text

    return {
        "attendee": attendee,
        "attendee_token": login(client, "room-member@example.com"),
        "second_token": login(client, "room-second@example.com"),
        "outsider_token": login(client, "room-outsider@example.com"),
        "meeting": meeting,
    }


def test_valid_participant_receives_livekit_connection(client):
    data = setup_meeting(client)
    meeting_id = data["meeting"]["public_id"]
    response = client.post(
        f"/api/v1/meetings/{meeting_id}/room/connect",
        headers=auth_headers(data["attendee_token"]),
    )
    body = response.json()
    assert response.status_code == 200, response.text
    assert body["livekit_url"] == settings.LIVEKIT_URL
    assert body["room_name"] == f"meeting-{meeting_id}"
    assert body["participant"]["user_public_id"] == data["attendee"]["public_id"]
    assert settings.LIVEKIT_API_SECRET not in response.text


def test_unauthorized_participant_cannot_connect(client):
    data = setup_meeting(client)
    response = client.post(
        f"/api/v1/meetings/{data['meeting']['public_id']}/room/connect",
        headers=auth_headers(data["outsider_token"]),
    )
    assert response.status_code == 403


def test_joining_records_authenticated_participant_time(client):
    data = setup_meeting(client)
    meeting_id = data["meeting"]["public_id"]
    response = client.post(
        f"/api/v1/meetings/{meeting_id}/room/join",
        headers=auth_headers(data["attendee_token"]),
    )
    body = response.json()
    assert response.status_code == 200, response.text
    assert body["user_public_id"] == data["attendee"]["public_id"]
    assert body["status"] == "JOINED"
    assert body["join_time"] is not None
    assert body["leave_time"] is None


def test_leaving_records_leave_time_and_duration(client):
    data = setup_meeting(client)
    meeting_id = data["meeting"]["public_id"]
    client.post(f"/api/v1/meetings/{meeting_id}/room/join", headers=auth_headers(data["attendee_token"]))
    response = client.post(
        f"/api/v1/meetings/{meeting_id}/room/leave",
        headers=auth_headers(data["attendee_token"]),
    )
    body = response.json()
    assert response.status_code == 200, response.text
    assert body["status"] == "LEFT"
    assert body["leave_time"] is not None
    assert body["attendance_duration_seconds"] is not None
    assert body["attendance_duration_seconds"] >= 0


def test_multiple_participants_have_distinct_connection_identities(client):
    data = setup_meeting(client)
    meeting_id = data["meeting"]["public_id"]
    first = client.post(
        f"/api/v1/meetings/{meeting_id}/room/connect",
        headers=auth_headers(data["attendee_token"]),
    ).json()
    second = client.post(
        f"/api/v1/meetings/{meeting_id}/room/connect",
        headers=auth_headers(data["second_token"]),
    ).json()
    first_claims = jwt.decode(first["token"], settings.LIVEKIT_API_SECRET, algorithms=["HS256"])
    second_claims = jwt.decode(second["token"], settings.LIVEKIT_API_SECRET, algorithms=["HS256"])
    assert first_claims["video"]["room"] == f"meeting-{meeting_id}"
    assert second_claims["video"]["room"] == f"meeting-{meeting_id}"
    assert first_claims["sub"] != second_claims["sub"]


def test_token_security_claims_are_scoped_to_meeting(client):
    data = setup_meeting(client)
    meeting_id = data["meeting"]["public_id"]
    response = client.post(
        f"/api/v1/meetings/{meeting_id}/room/connect",
        headers=auth_headers(data["attendee_token"]),
    )
    claims = jwt.decode(response.json()["token"], settings.LIVEKIT_API_SECRET, algorithms=["HS256"])
    assert claims["iss"] == settings.LIVEKIT_API_KEY
    meta = json.loads(claims["metadata"]) if isinstance(claims["metadata"], str) else claims["metadata"]
    assert meta["user_public_id"] == data["attendee"]["public_id"]
    assert meta["meeting_id"] == meeting_id
    assert claims["video"] == {
        "room": f"meeting-{meeting_id}",
        "roomJoin": True,
        "canPublish": True,
        "canSubscribe": True,
        "canPublishData": True,
    }
