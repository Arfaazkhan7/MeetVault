"""
Comprehensive Security Test Suite for MeetVault Administrator Authorization & Privilege Escalation Prevention.

Verifies:
1. Public registration rejects any attempt to self-assign 'admin', 'SUPER_ADMIN', 'COMPANY_ADMIN', or invalid account types (HTTP 422).
2. Users registered publicly with administrator-like emails ('system.admin@meetvault.com', 'admin@meetvault.com') are strictly 'personal' users and cannot login to /api/v1/admin/login (HTTP 403).
3. Public /api/v1/admin/login does not auto-seed or create accounts with default credentials on failed login.
4. Administrative endpoints (/workspaces, /stats) require trusted DB account_type=='admin' and reject non-admin bearer tokens (HTTP 403).
5. Maintenance endpoints (/recordings/reconcile-orphans) reject users with admin emails unless backed by trusted server-side roles.
6. Server-side explicit provisioning via provision_admin_user creates verified admins that can successfully authenticate and access admin tools.
7. Admin CLI management tool (app.cli.admin) functions correctly.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.user import User
from app.core.tokens import create_token
from app.services.user_service import provision_admin_user, get_user_by_email
from tests.conftest import TestingSessionLocal

client = TestClient(app)


def test_public_registration_rejects_privileged_account_types():
    """Requirement 2 & 3: Ensure public registration can never assign 'admin' or privileged roles."""
    malicious_payloads = [
        {"email": "attacker1@evil.com", "password": "Password123!", "full_name": "Attacker 1", "account_type": "admin"},
        {"email": "attacker2@evil.com", "password": "Password123!", "full_name": "Attacker 2", "account_type": "SUPER_ADMIN"},
        {"email": "attacker3@evil.com", "password": "Password123!", "full_name": "Attacker 3", "account_type": "COMPANY_ADMIN"},
        {"email": "attacker4@evil.com", "password": "Password123!", "full_name": "Attacker 4", "account_type": "root"},
    ]

    for payload in malicious_payloads:
        resp = client.post("/api/v1/auth/register", json=payload)
        assert resp.status_code == 422, f"Expected 422 for account_type '{payload['account_type']}', got {resp.status_code}: {resp.text}"
        assert "account_type" in resp.text.lower()


def test_public_registration_only_allows_personal_and_organization():
    """Requirement 3: Enforce permitted account types on the server independently of client input."""
    # Valid personal
    resp_personal = client.post("/api/v1/auth/register", json={
        "email": "legit.personal@example.com",
        "password": "Password123!",
        "full_name": "Legit Personal",
        "account_type": "personal",
    })
    assert resp_personal.status_code == 201

    # Valid organization
    resp_org = client.post("/api/v1/auth/register", json={
        "email": "legit.org@example.com",
        "password": "Password123!",
        "full_name": "Legit Org",
        "account_type": "organization",
        "organization_name": "Legit Corp",
    })
    assert resp_org.status_code == 201


def test_unprivileged_user_with_admin_email_cannot_login_as_admin():
    """Requirement 4: Remove automatic administrator promotion based solely on an email address."""
    admin_spoof_email = "system.admin@meetvault.com"
    spoof_password = "AttackerPassword123!"

    # Attacker registers publicly with the system admin email
    reg = client.post("/api/v1/auth/register", json={
        "email": admin_spoof_email,
        "password": spoof_password,
        "full_name": "Admin Impersonator",
        "account_type": "personal",
    })
    assert reg.status_code == 201

    # Attacker attempts admin login - MUST be rejected with 403 Forbidden
    login_resp = client.post("/api/v1/admin/login", json={
        "email": admin_spoof_email,
        "password": spoof_password,
    })
    assert login_resp.status_code == 403
    assert "This account does not have admin privileges" in login_resp.json()["detail"]


def test_no_hardcoded_admin_auto_seed_on_admin_login():
    """Requirement 5: Remove hardcoded default passwords and auto-creation from admin login."""
    # Hitting admin login with the old hardcoded default credentials when user doesn't exist
    resp = client.post("/api/v1/admin/login", json={
        "email": "unseeded.admin@meetvault.com",
        "password": "AdminPassword123!",
    })
    # Must fail with 401 Unauthorized, NEVER automatically create or promote an admin account
    assert resp.status_code == 401
    assert "Invalid admin credentials" in resp.json()["detail"]


def test_admin_endpoints_strictly_enforce_database_account_type():
    """Requirement 7: Admin endpoints strictly enforce administrator authorization based on trusted database attributes."""
    db = TestingSessionLocal()
    try:
        # Create a regular user who has a token
        regular_user = User(
            public_id="usr-test-regular-1",
            email="system.admin.lookalike@meetvault.com",
            full_name="Lookalike",
            hashed_password="hash",
            account_type="personal",
        )
        db.add(regular_user)
        db.commit()
    finally:
        db.close()

    token = create_token(subject="usr-test-regular-1", token_type="access")
    headers = {"Authorization": f"Bearer {token}"}

    # Cannot access /api/v1/admin/workspaces
    resp_ws = client.get("/api/v1/admin/workspaces", headers=headers)
    assert resp_ws.status_code == 403
    assert "Requires System Admin privileges" in resp_ws.json()["detail"]

    # Cannot access /api/v1/admin/stats
    resp_stats = client.get("/api/v1/admin/stats", headers=headers)
    assert resp_stats.status_code == 403
    assert "Requires System Admin privileges" in resp_stats.json()["detail"]

    # Cannot access /api/v1/recordings/reconcile-orphans
    resp_rec = client.post("/api/v1/recordings/reconcile-orphans", headers=headers)
    assert resp_rec.status_code == 403


def test_secure_admin_provisioning_and_full_admin_access():
    """Requirement 6 & 8: Explicit provisioning works securely and legitimate admins can access endpoints."""
    admin_email = "real.sysadmin@meetvault.com"
    admin_password = "SuperSecurePassword123!"

    db = TestingSessionLocal()
    try:
        admin_user = provision_admin_user(
            db=db,
            email=admin_email,
            plain_password=admin_password,
            full_name="Real System Admin",
        )
        assert admin_user.account_type == "admin"
    finally:
        db.close()

    # Admin logs in via /api/v1/admin/login
    login_resp = client.post("/api/v1/admin/login", json={
        "email": admin_email,
        "password": admin_password,
    })
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Legitimate admin can access /stats
    stats_resp = client.get("/api/v1/admin/stats", headers=headers)
    assert stats_resp.status_code == 200
    assert "total_users" in stats_resp.json()

    # Legitimate admin can access /workspaces
    ws_resp = client.get("/api/v1/admin/workspaces", headers=headers)
    assert ws_resp.status_code == 200
    assert isinstance(ws_resp.json(), list)


def test_admin_cli_tool():
    """Requirement 6: Verify administrative CLI tool provisions and manages admins correctly."""
    from app.cli.admin import cmd_provision, cmd_demote, cmd_list
    from unittest.mock import MagicMock

    args_prov = MagicMock()
    args_prov.email = "cli.admin@meetvault.com"
    args_prov.password = "CliAdminPass123!"
    args_prov.name = "CLI Admin"

    # Provision admin via CLI handler
    db = TestingSessionLocal()
    try:
        cmd_provision(args_prov, db=db)
        user = get_user_by_email(db, "cli.admin@meetvault.com")
        assert user is not None
        assert user.account_type == "admin"

        # Demote admin via CLI handler
        args_demote = MagicMock()
        args_demote.email = "cli.admin@meetvault.com"
        cmd_demote(args_demote, db=db)

        user_demoted = get_user_by_email(db, "cli.admin@meetvault.com")
        assert user_demoted.account_type == "personal"
    finally:
        db.close()
