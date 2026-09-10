"""Phase 5 - Meeting Management Tests - test DB provided by conftest.py"""
from datetime import datetime, timezone

def register(client, email, name="Test User", password="StrongPass1"):
    r = client.post("/api/v1/auth/register", json={
        "full_name": name, "email": email, "password": password,
    })
    assert r.status_code == 201, r.text
    return r.json()

def login(client, email, password="StrongPass1"):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]

def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}

def setup_scenario(client):
    # A: Company Admin
    admin = register(client, "admin@example.com")
    token = login(client, "admin@example.com")
    comp = client.post("/api/v1/companies", json={"name": "Acme Corp"}, headers=auth_headers(token)).json()
    cid = comp["public_id"]

    # B: Normal member
    mem1 = register(client, "mem1@example.com")
    client.post(f"/api/v1/companies/{cid}/members", json={"email": "mem1@example.com", "role": "MEMBER"}, headers=auth_headers(token))

    # Project
    proj = client.post(f"/api/v1/companies/{cid}/projects", json={"name": "Alpha"}, headers=auth_headers(token)).json()

    return token, cid, admin, mem1, proj["public_id"]

def test_create_meeting(client):
    token, cid, admin, _, pid = setup_scenario(client)
    r = client.post(f"/api/v1/companies/{cid}/meetings", json={
        "title": "Daily Standup",
        "project_id": pid
    }, headers=auth_headers(token))
    assert r.status_code == 201
    m = r.json()
    assert m["title"] == "Daily Standup"
    assert m["status"] == "SCHEDULED"
    assert m["public_id"].startswith("MTG-")

    # Creator is HOST
    parts = client.get(f"/api/v1/meetings/{m['public_id']}/participants", headers=auth_headers(token)).json()
    assert len(parts) == 1
    assert parts[0]["user_public_id"] == admin["public_id"]
    assert parts[0]["role"] == "HOST"
    assert parts[0]["status"] == "INVITED"

def test_update_meeting_status(client):
    token, cid, _, _, pid = setup_scenario(client)
    m = client.post(f"/api/v1/companies/{cid}/meetings", json={"title": "M1", "project_id": pid}, headers=auth_headers(token)).json()

    r = client.patch(f"/api/v1/meetings/{m['public_id']}", json={"status": "LIVE"}, headers=auth_headers(token))
    assert r.status_code == 200
    assert r.json()["status"] == "LIVE"

def test_invite_and_status(client):
    token, cid, admin, mem1, pid = setup_scenario(client)
    m = client.post(f"/api/v1/companies/{cid}/meetings", json={"title": "M1", "project_id": pid}, headers=auth_headers(token)).json()
    mid = m["public_id"]

    # Invite mem1
    r = client.post(f"/api/v1/meetings/{mid}/participants", json={
        "user_public_id": mem1["public_id"],
        "role": "ATTENDEE"
    }, headers=auth_headers(token))
    assert r.status_code == 201
    assert r.json()["status"] == "INVITED"

    # mem1 joins meeting
    token_mem1 = login(client, "mem1@example.com")
    now_str = datetime.now(timezone.utc).isoformat()

    r2 = client.patch(f"/api/v1/meetings/{mid}/participants/{mem1['public_id']}", json={
        "status": "JOINED",
        "join_time": now_str
    }, headers=auth_headers(token_mem1))
    assert r2.status_code == 200
    assert r2.json()["status"] == "JOINED"

def test_cross_company_isolation_meetings(client):
    tokenA, cidA, _, _, pidA = setup_scenario(client)
    mA = client.post(f"/api/v1/companies/{cidA}/meetings", json={"title": "M1", "project_id": pidA}, headers=auth_headers(tokenA)).json()

    # User B makes Company B
    register(client, "userb@example.com")
    tokenB = login(client, "userb@example.com")

    # User B tries to access Meeting A
    r = client.get(f"/api/v1/meetings/{mA['public_id']}", headers=auth_headers(tokenB))
    assert r.status_code == 403

