"""Phase 4 - Project Management Tests - test DB provided by conftest.py"""

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

    return token, cid, admin, mem1

def test_create_project_as_admin(client):
    token, cid, admin, _ = setup_scenario(client)
    r = client.post(f"/api/v1/companies/{cid}/projects", json={"name": "Alpha"}, headers=auth_headers(token))
    assert r.status_code == 201
    p = r.json()
    assert p["name"] == "Alpha"
    assert p["status"] == "ACTIVE"
    assert p["company_id"] == cid
    assert p["public_id"].startswith("PRJ-")

def test_create_project_insufficient_role(client):
    _, cid, _, mem1 = setup_scenario(client)
    token = login(client, "mem1@example.com")
    r = client.post(f"/api/v1/companies/{cid}/projects", json={"name": "Beta"}, headers=auth_headers(token))
    assert r.status_code == 403

def test_get_project_and_list(client):
    token, cid, _, _ = setup_scenario(client)
    p = client.post(f"/api/v1/companies/{cid}/projects", json={"name": "Alpha"}, headers=auth_headers(token)).json()
    pid = p["public_id"]

    r = client.get(f"/api/v1/projects/{pid}", headers=auth_headers(token))
    assert r.status_code == 200
    assert r.json()["name"] == "Alpha"

    lst = client.get(f"/api/v1/companies/{cid}/projects", headers=auth_headers(token)).json()
    assert len(lst) == 1

def test_cross_company_isolation(client):
    tokenA, cidA, _, _ = setup_scenario(client)
    p = client.post(f"/api/v1/companies/{cidA}/projects", json={"name": "Alpha"}, headers=auth_headers(tokenA)).json()
    pid = p["public_id"]

    # User B makes Company B
    register(client, "userb@example.com")
    tokenB = login(client, "userb@example.com")
    compB = client.post("/api/v1/companies", json={"name": "Beta Corp"}, headers=auth_headers(tokenB)).json()

    # User B tries to access Project Alpha
    r = client.get(f"/api/v1/projects/{pid}", headers=auth_headers(tokenB))
    assert r.status_code == 403

def test_update_and_archive(client):
    token, cid, _, _ = setup_scenario(client)
    p = client.post(f"/api/v1/companies/{cid}/projects", json={"name": "Alpha"}, headers=auth_headers(token)).json()
    pid = p["public_id"]

    r = client.patch(f"/api/v1/projects/{pid}", json={"name": "Alpha V2"}, headers=auth_headers(token))
    assert r.status_code == 200
    assert r.json()["name"] == "Alpha V2"

    r = client.post(f"/api/v1/projects/{pid}/archive", headers=auth_headers(token))
    assert r.status_code == 200
    assert r.json()["status"] == "ARCHIVED"

    # Check listing active doesn't return it (unless specified)
    lst = client.get(f"/api/v1/companies/{cid}/projects?status=ACTIVE", headers=auth_headers(token)).json()
    assert len(lst) == 0

def test_project_members(client):
    token, cid, _, mem1 = setup_scenario(client)
    p = client.post(f"/api/v1/companies/{cid}/projects", json={"name": "Alpha"}, headers=auth_headers(token)).json()
    pid = p["public_id"]

    r = client.post(f"/api/v1/projects/{pid}/members", json={"user_public_id": mem1["public_id"], "role": "MEMBER"}, headers=auth_headers(token))
    assert r.status_code == 201

    mems = client.get(f"/api/v1/projects/{pid}/members", headers=auth_headers(token)).json()
    # Admin is auto-added, plus mem1
    assert len(mems) == 2

    client.delete(f"/api/v1/projects/{pid}/members/{mem1['public_id']}", headers=auth_headers(token))
    mems = client.get(f"/api/v1/projects/{pid}/members", headers=auth_headers(token)).json()
    assert len(mems) == 1

