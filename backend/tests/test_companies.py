"""Phase 3 - Company and User Management Tests - test DB provided by conftest.py"""


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def create_company(client, token, name="Acme Corp", domain=None):
    r = client.post("/api/v1/companies", json={"name": name, "domain": domain},
                    headers=auth_headers(token))
    assert r.status_code == 201, r.text
    return r.json()


# ─────────────────────────────────────────────────────────────────────────────
# Company creation
# ─────────────────────────────────────────────────────────────────────────────

class TestCompanyCreation:
    def test_create_company_success(self, client):
        register(client, "alice@example.com")
        token = login(client, "alice@example.com")
        company = create_company(client, token)
        assert company["public_id"].startswith("COMP-")
        assert company["name"] == "Acme Corp"

    def test_create_company_requires_auth(self, client):
        r = client.post("/api/v1/companies", json={"name": "Ghost Corp"})
        assert r.status_code == 401

    def test_create_company_blank_name(self, client):
        register(client, "bob@example.com")
        token = login(client, "bob@example.com")
        r = client.post("/api/v1/companies", json={"name": "   "},
                        headers=auth_headers(token))
        assert r.status_code == 422

    def test_creator_becomes_company_admin(self, client):
        register(client, "alice@example.com")
        token = login(client, "alice@example.com")
        company = create_company(client, token)
        members = client.get(
            f"/api/v1/companies/{company['public_id']}/members",
            headers=auth_headers(token),
        ).json()
        assert len(members) == 1
        assert members[0]["role"] == "COMPANY_ADMIN"

    def test_list_my_companies(self, client):
        register(client, "alice@example.com")
        token = login(client, "alice@example.com")
        create_company(client, token, "Company A")
        create_company(client, token, "Company B")
        r = client.get("/api/v1/companies", headers=auth_headers(token))
        assert r.status_code == 200
        custom_companies = [c for c in r.json() if "Personal Workspace" not in c["name"]]
        assert len(custom_companies) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Member management
# ─────────────────────────────────────────────────────────────────────────────

class TestMemberManagement:
    def _setup(self, client):
        register(client, "admin@example.com", "Admin User")
        register(client, "member@example.com", "Member User")
        admin_token = login(client, "admin@example.com")
        company = create_company(client, admin_token)
        return admin_token, company["public_id"]

    def test_add_member_success(self, client):
        admin_token, cid = self._setup(client)
        r = client.post(
            f"/api/v1/companies/{cid}/members",
            json={"email": "member@example.com", "role": "MEMBER"},
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 201, r.text
        assert r.json()["role"] == "MEMBER"

    def test_add_member_nonexistent_user(self, client):
        admin_token, cid = self._setup(client)
        r = client.post(
            f"/api/v1/companies/{cid}/members",
            json={"email": "nobody@example.com", "role": "MEMBER"},
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 404

    def test_add_member_duplicate_rejected(self, client):
        admin_token, cid = self._setup(client)
        payload = {"email": "member@example.com", "role": "MEMBER"}
        client.post(f"/api/v1/companies/{cid}/members", json=payload,
                    headers=auth_headers(admin_token))
        r = client.post(f"/api/v1/companies/{cid}/members", json=payload,
                        headers=auth_headers(admin_token))
        assert r.status_code == 409

    def test_update_member_role(self, client):
        admin_token, cid = self._setup(client)
        client.post(f"/api/v1/companies/{cid}/members",
                    json={"email": "member@example.com", "role": "MEMBER"},
                    headers=auth_headers(admin_token))
        members = client.get(f"/api/v1/companies/{cid}/members",
                             headers=auth_headers(admin_token)).json()
        member_uid = next(m["user_public_id"] for m in members if "member@" in m["email"])
        r = client.patch(
            f"/api/v1/companies/{cid}/members/{member_uid}",
            json={"role": "PROJECT_MANAGER"},
            headers=auth_headers(admin_token),
        )
        assert r.status_code == 200
        assert r.json()["role"] == "PROJECT_MANAGER"

    def test_remove_member(self, client):
        admin_token, cid = self._setup(client)
        client.post(f"/api/v1/companies/{cid}/members",
                    json={"email": "member@example.com", "role": "MEMBER"},
                    headers=auth_headers(admin_token))
        members = client.get(f"/api/v1/companies/{cid}/members",
                             headers=auth_headers(admin_token)).json()
        member_uid = next(m["user_public_id"] for m in members if "member@" in m["email"])
        r = client.delete(f"/api/v1/companies/{cid}/members/{member_uid}",
                          headers=auth_headers(admin_token))
        assert r.status_code == 204
        members_after = client.get(f"/api/v1/companies/{cid}/members",
                                   headers=auth_headers(admin_token)).json()
        assert all(m["email"] != "member@example.com" for m in members_after)

    def test_cannot_remove_self(self, client):
        admin_token, cid = self._setup(client)
        members = client.get(f"/api/v1/companies/{cid}/members",
                             headers=auth_headers(admin_token)).json()
        admin_uid = members[0]["user_public_id"]
        r = client.delete(f"/api/v1/companies/{cid}/members/{admin_uid}",
                          headers=auth_headers(admin_token))
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Authorization and role enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestAuthorization:
    def _setup(self, client):
        register(client, "admin@example.com", "Admin")
        register(client, "member@example.com", "Member")
        admin_token = login(client, "admin@example.com")
        member_token = login(client, "member@example.com")
        company = create_company(client, admin_token)
        cid = company["public_id"]
        client.post(f"/api/v1/companies/{cid}/members",
                    json={"email": "member@example.com", "role": "MEMBER"},
                    headers=auth_headers(admin_token))
        return admin_token, member_token, cid

    def test_member_can_view_members(self, client):
        _, member_token, cid = self._setup(client)
        r = client.get(f"/api/v1/companies/{cid}/members",
                       headers=auth_headers(member_token))
        assert r.status_code == 200

    def test_member_cannot_add_members(self, client):
        _, member_token, cid = self._setup(client)
        register(client, "newuser@example.com")
        r = client.post(f"/api/v1/companies/{cid}/members",
                        json={"email": "newuser@example.com", "role": "MEMBER"},
                        headers=auth_headers(member_token))
        assert r.status_code == 403

    def test_member_cannot_remove_members(self, client):
        admin_token, member_token, cid = self._setup(client)
        members = client.get(f"/api/v1/companies/{cid}/members",
                             headers=auth_headers(admin_token)).json()
        admin_uid = next(m["user_public_id"] for m in members if "admin@" in m["email"])
        r = client.delete(f"/api/v1/companies/{cid}/members/{admin_uid}",
                          headers=auth_headers(member_token))
        assert r.status_code == 403

    def test_unauthenticated_cannot_view_members(self, client):
        register(client, "admin@example.com")
        token = login(client, "admin@example.com")
        company = create_company(client, token)
        r = client.get(f"/api/v1/companies/{company['public_id']}/members")
        assert r.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# Cross-company isolation
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossCompanyIsolation:
    def test_user_from_company_a_cannot_see_company_b_members(self, client):
        register(client, "usera@example.com", "User A")
        token_a = login(client, "usera@example.com")
        create_company(client, token_a, "Company A")

        register(client, "userb@example.com", "User B")
        token_b = login(client, "userb@example.com")
        company_b = create_company(client, token_b, "Company B")

        r = client.get(
            f"/api/v1/companies/{company_b['public_id']}/members",
            headers=auth_headers(token_a),
        )
        assert r.status_code == 403

    def test_user_from_company_a_cannot_add_to_company_b(self, client):
        register(client, "usera@example.com")
        token_a = login(client, "usera@example.com")
        register(client, "userb@example.com")
        token_b = login(client, "userb@example.com")
        company_b = create_company(client, token_b, "Company B")

        r = client.post(
            f"/api/v1/companies/{company_b['public_id']}/members",
            json={"email": "usera@example.com", "role": "MEMBER"},
            headers=auth_headers(token_a),
        )
        assert r.status_code == 403

    def test_each_user_only_sees_own_companies(self, client):
        register(client, "usera@example.com")
        token_a = login(client, "usera@example.com")
        create_company(client, token_a, "Company A")

        register(client, "userb@example.com")
        token_b = login(client, "userb@example.com")
        create_company(client, token_b, "Company B")

        companies_a = client.get("/api/v1/companies", headers=auth_headers(token_a)).json()
        companies_b = client.get("/api/v1/companies", headers=auth_headers(token_b)).json()

        custom_a = [c for c in companies_a if "Personal Workspace" not in c["name"]]
        custom_b = [c for c in companies_b if "Personal Workspace" not in c["name"]]

        assert all(c["name"] == "Company A" for c in custom_a)
        assert all(c["name"] == "Company B" for c in custom_b)


# ─────────────────────────────────────────────────────────────────────────────
# User profile
# ─────────────────────────────────────────────────────────────────────────────

class TestUserProfile:
    def test_get_profile(self, client):
        register(client, "alice@example.com", "Alice")
        token = login(client, "alice@example.com")
        r = client.get("/api/v1/users/me", headers=auth_headers(token))
        assert r.status_code == 200
        assert r.json()["email"] == "alice@example.com"
        assert "hashed_password" not in r.text

    def test_update_profile(self, client):
        register(client, "alice@example.com", "Alice")
        token = login(client, "alice@example.com")
        r = client.patch(
            "/api/v1/users/me",
            json={"full_name": "Alice Updated", "phone": "+91-9999999999"},
            headers=auth_headers(token),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["full_name"] == "Alice Updated"
        assert body["phone"] == "+91-9999999999"

    def test_profile_requires_auth(self, client):
        r = client.get("/api/v1/users/me")
        assert r.status_code == 401
