import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_admin_workspace_creation_flow():
    # 1. Register System Admin
    admin_email = "system.admin@meetvault.com"
    admin_pass = "SysAdminPass123!"
    reg = client.post("/api/v1/auth/register", json={
        "email": admin_email,
        "password": admin_pass,
        "full_name": "System Admin",
        "account_type": "personal"
    })
    assert reg.status_code == 201, reg.text

    # 2. Login Admin
    login_a = client.post("/api/v1/admin/login", json={
        "email": admin_email,
        "password": admin_pass
    })
    assert login_a.status_code == 200, login_a.text
    token = login_a.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Create Organization/Workspace by Admin
    org_req = {
        "organization_name": "Globex Corporation",
        "admin_name": "Hank Scorpio",
        "admin_email": "scorpio@globex.com",
        "admin_password": "ScorpioPass123!"
    }
    create_ws = client.post("/api/v1/admin/workspaces", json=org_req, headers=headers)
    assert create_ws.status_code == 201, create_ws.text
    ws_data = create_ws.json()
    assert ws_data["organization_name"] == "Globex Corporation"
    assert ws_data["workspace_code"].startswith("MV-")
    assert ws_data["admin_email"] == "scorpio@globex.com"

    # 4. Workspace Admin Login with generated workspace_code
    login_ws_admin = client.post("/api/v1/auth/login/workspace", json={
        "workspace_code": ws_data["workspace_code"],
        "email": "scorpio@globex.com",
        "password": "ScorpioPass123!"
    })
    assert login_ws_admin.status_code == 200, login_ws_admin.text

    # 5. Fetch Admin System Stats
    stats = client.get("/api/v1/admin/stats", headers=headers)
    assert stats.status_code == 200, stats.text
    s_data = stats.json()
    assert s_data["total_workspaces"] >= 1
    assert s_data["total_users"] >= 2
