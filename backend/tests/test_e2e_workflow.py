import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_full_end_to_end_meeting_workflow():
    # 1. Register User 1 (Host)
    host_email = "host_e2e@example.com"
    host_pass = "HostPass123!"
    reg1 = client.post("/api/v1/auth/register", json={
        "email": host_email,
        "password": host_pass,
        "full_name": "Host User"
    })
    assert reg1.status_code == 201, reg1.text
    host_data = reg1.json()
    assert host_data["email"] == host_email

    # 2. Login User 1
    login1 = client.post("/api/v1/auth/login", json={
        "email": host_email,
        "password": host_pass
    })
    assert login1.status_code == 200, login1.text
    host_token = login1.json()["access_token"]
    host_headers = {"Authorization": f"Bearer {host_token}"}

    # 3. Get Host's auto-created Company & Project
    comp_resp = client.get("/api/v1/companies", headers=host_headers)
    assert comp_resp.status_code == 200, comp_resp.text
    companies = comp_resp.json()
    assert len(companies) > 0
    company_id = companies[0]["public_id"]

    proj_resp = client.get(f"/api/v1/companies/{company_id}/projects", headers=host_headers)
    assert proj_resp.status_code == 200, proj_resp.text
    projects = proj_resp.json()
    assert len(projects) > 0
    project_id = projects[0]["public_id"]

    # 4. Host creates an Instant Meeting
    create_mtg = client.post(
        f"/api/v1/companies/{company_id}/meetings",
        json={
            "title": "E2E Instant Sync",
            "project_id": project_id
        },
        headers=host_headers
    )
    assert create_mtg.status_code == 201, create_mtg.text
    mtg_data = create_mtg.json()
    meeting_id = mtg_data["public_id"]
    invite_code = mtg_data["invite_code"]
    assert invite_code is not None

    # 5. Host starts meeting
    start_mtg = client.post(f"/api/v1/meetings/{meeting_id}/start", headers=host_headers)
    assert start_mtg.status_code == 200, start_mtg.text
    assert start_mtg.json()["status"] == "LIVE"

    # 6. Host connects & joins room
    conn_host = client.post(f"/api/v1/meetings/{meeting_id}/room/connect", headers=host_headers)
    assert conn_host.status_code == 200, conn_host.text
    assert "token" in conn_host.json()

    join_host = client.post(f"/api/v1/meetings/{meeting_id}/room/join", headers=host_headers)
    assert join_host.status_code == 200, join_host.text

    # 7. Register User 2 (Participant)
    part_email = "part_e2e@example.com"
    part_pass = "PartPass123!"
    reg2 = client.post("/api/v1/auth/register", json={
        "email": part_email,
        "password": part_pass,
        "full_name": "Participant User"
    })
    assert reg2.status_code == 201, reg2.text

    # 8. Login User 2
    login2 = client.post("/api/v1/auth/login", json={
        "email": part_email,
        "password": part_pass
    })
    assert login2.status_code == 200, login2.text
    part_token = login2.json()["access_token"]
    part_headers = {"Authorization": f"Bearer {part_token}"}

    # 9. Participant joins meeting via Invite Code
    join_code = client.post("/api/v1/meetings/join", json={"invite_code": invite_code}, headers=part_headers)
    assert join_code.status_code == 200, join_code.text
    code_data = join_code.json()
    assert code_data["meeting_id"] == meeting_id
    assert "token" in code_data

    # 10. Participant joins room
    join_part = client.post(f"/api/v1/meetings/{meeting_id}/room/join", headers=part_headers)
    assert join_part.status_code == 200, join_part.text

    # 11. Check participants list — BOTH Host and Participant must be listed
    parts_resp = client.get(f"/api/v1/meetings/{meeting_id}/participants", headers=host_headers)
    assert parts_resp.status_code == 200, parts_resp.text
    participants = parts_resp.json()
    assert len(participants) == 2
    roles = {p["user_public_id"]: p["role"] for p in participants}
    assert host_data["public_id"] in roles
    assert reg2.json()["public_id"] in roles

    # 12. Participant leaves room
    leave_part = client.post(f"/api/v1/meetings/{meeting_id}/room/leave", headers=part_headers)
    assert leave_part.status_code == 200, leave_part.text

    # 13. Host ends meeting
    end_mtg = client.post(f"/api/v1/meetings/{meeting_id}/end", headers=host_headers)
    assert end_mtg.status_code == 200, end_mtg.text

    # 14. Verify Meeting History shows COMPLETED
    history = client.get(f"/api/v1/companies/{company_id}/meetings", headers=host_headers)
    assert history.status_code == 200, history.text
    h_meetings = history.json()
    target = next(m for m in h_meetings if m["public_id"] == meeting_id)
    assert target["status"] == "COMPLETED"
