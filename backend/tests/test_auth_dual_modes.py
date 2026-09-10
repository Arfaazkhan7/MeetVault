import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_personal_login_flow():
    email = "personal_mode@example.com"
    password = "PersonalPass123!"
    
    # 1. Register User
    reg = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "full_name": "Personal Tester",
        "account_type": "personal"
    })
    assert reg.status_code == 201, reg.text

    # 2. Login Personal Mode (No workspace ID required)
    login_p = client.post("/api/v1/auth/login/personal", json={
        "email": email,
        "password": password
    })
    assert login_p.status_code == 200, login_p.text
    res = login_p.json()
    assert "access_token" in res

def test_workspace_login_flow():
    email = "workspace_mode@example.com"
    password = "WorkspacePass123!"
    org_name = "Acme Corp"

    # 1. Register User with Organization
    reg = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "full_name": "Workspace Tester",
        "account_type": "organization",
        "organization_name": org_name
    })
    assert reg.status_code == 201, reg.text
    user_data = reg.json()

    # 2. Fetch User's Workspace public_id
    login_p = client.post("/api/v1/auth/login/personal", json={
        "email": email,
        "password": password
    })
    assert login_p.status_code == 200
    token = login_p.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    comp_resp = client.get("/api/v1/companies", headers=headers)
    assert comp_resp.status_code == 200
    companies = comp_resp.json()
    assert len(companies) > 0
    workspace_code = companies[0]["public_id"]

    # 3. Login Workspace Mode
    login_w = client.post("/api/v1/auth/login/workspace", json={
        "workspace_code": workspace_code,
        "email": email,
        "password": password
    })
    assert login_w.status_code == 200, login_w.text
    res_w = login_w.json()
    assert "access_token" in res_w
    assert res_w["workspace_id"] == workspace_code

    # 4. Attempt Workspace Login with invalid workspace code -> 401
    login_fail = client.post("/api/v1/auth/login/workspace", json={
        "workspace_code": "INVALID_WS_CODE",
        "email": email,
        "password": password
    })
    assert login_fail.status_code == 401
