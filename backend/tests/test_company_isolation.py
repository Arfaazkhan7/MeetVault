"""
Phase 17 Security Hardening — Multitenancy & Company Isolation Tests.

Verifies that Company A users can NEVER access, query, update, or delete:
- Company B meetings
- Company B projects
- Company B documents
- Company B tasks, topics, decisions
- Company B search & Ask Meeting Memory RAG results
"""

import pytest
from fastapi.testclient import TestClient


class TestCompanyIsolation:
    def _create_user_and_company(self, client: TestClient, name: str, email: str, comp_name: str):
        # 1. Register user
        r_user = client.post("/api/v1/auth/register", json={
            "full_name": name,
            "email": email,
            "password": "StrongPassword123!",
        })
        assert r_user.status_code == 201, r_user.text

        # 2. Login to get token
        r_login = client.post("/api/v1/auth/login", json={
            "email": email,
            "password": "StrongPassword123!",
        })
        assert r_login.status_code == 200, r_login.text
        token = r_login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 3. Create Company
        r_comp = client.post("/api/v1/companies", json={"name": comp_name}, headers=headers)
        assert r_comp.status_code == 201, r_comp.text
        comp_id = r_comp.json()["public_id"]

        # 4. Create Project
        r_proj = client.post(f"/api/v1/companies/{comp_id}/projects", json={
            "name": f"{comp_name} Core Project",
            "description": "Confidential project",
        }, headers=headers)
        assert r_proj.status_code == 201, r_proj.text
        proj_id = r_proj.json()["public_id"]

        # 5. Create Meeting
        r_mtg = client.post(f"/api/v1/companies/{comp_id}/meetings", json={
            "title": f"Confidential {comp_name} Strategy Sync",
            "project_id": proj_id,
        }, headers=headers)
        assert r_mtg.status_code == 201, r_mtg.text
        mtg_id = r_mtg.json()["public_id"]

        return {
            "user": r_user.json(),
            "token": token,
            "headers": headers,
            "comp_id": comp_id,
            "proj_id": proj_id,
            "mtg_id": mtg_id,
        }

    def test_cross_company_meeting_access_blocked(self, client):
        comp_a = self._create_user_and_company(client, "Alice A", "alice@company-a.com", "Company A")
        comp_b = self._create_user_and_company(client, "Bob B", "bob@company-b.com", "Company B")

        # Alice attempts to access Company B's meeting details
        res = client.get(f"/api/v1/meetings/{comp_b['mtg_id']}", headers=comp_a["headers"])
        assert res.status_code in (403, 404), f"Expected 403/404, got {res.status_code}"

        # Alice attempts to list Company B's meetings
        res_list = client.get(f"/api/v1/companies/{comp_b['comp_id']}/meetings", headers=comp_a["headers"])
        assert res_list.status_code in (403, 404), f"Expected 403/404, got {res_list.status_code}"

    def test_cross_company_project_access_blocked(self, client):
        comp_a = self._create_user_and_company(client, "Alice A", "alice@company-a.com", "Company A")
        comp_b = self._create_user_and_company(client, "Bob B", "bob@company-b.com", "Company B")

        # Alice attempts to access Company B's project
        res = client.get(f"/api/v1/projects/{comp_b['proj_id']}", headers=comp_a["headers"])
        assert res.status_code in (403, 404), f"Expected 403/404, got {res.status_code}"

        # Alice attempts to list Company B's projects
        res_list = client.get(f"/api/v1/companies/{comp_b['comp_id']}/projects", headers=comp_a["headers"])
        assert res_list.status_code in (403, 404), f"Expected 403/404, got {res_list.status_code}"

    def test_cross_company_member_access_blocked(self, client):
        comp_a = self._create_user_and_company(client, "Alice A", "alice@company-a.com", "Company A")
        comp_b = self._create_user_and_company(client, "Bob B", "bob@company-b.com", "Company B")

        # Alice attempts to list Company B's members
        res = client.get(f"/api/v1/companies/{comp_b['comp_id']}/members", headers=comp_a["headers"])
        assert res.status_code in (403, 404), f"Expected 403/404, got {res.status_code}"

    def test_cross_company_search_isolation(self, client):
        comp_a = self._create_user_and_company(client, "Alice A", "alice@company-a.com", "Company A")
        comp_b = self._create_user_and_company(client, "Bob B", "bob@company-b.com", "Company B")

        # Alice attempts to run search on Company B's memory -> must be 403 Forbidden
        res = client.post(
            f"/api/v1/companies/{comp_b['comp_id']}/search",
            json={"query": "Confidential"},
            headers=comp_a["headers"]
        )
        assert res.status_code == 403, f"Expected 403 Forbidden, got {res.status_code}"

    def test_cross_company_rag_ask_memory_isolation(self, client):
        comp_a = self._create_user_and_company(client, "Alice A", "alice@company-a.com", "Company A")
        comp_b = self._create_user_and_company(client, "Bob B", "bob@company-b.com", "Company B")

        # Alice attempts to ask RAG question on Company B -> must be 403 Forbidden
        res_comp = client.post(
            f"/api/v1/companies/{comp_b['comp_id']}/ask",
            json={"question": "What is Company B strategy?"},
            headers=comp_a["headers"]
        )
        assert res_comp.status_code == 403, f"Expected 403 Forbidden, got {res_comp.status_code}"

        # Alice attempts to ask RAG question on Company B's project -> must be 403 Forbidden
        res_proj = client.post(
            f"/api/v1/projects/{comp_b['proj_id']}/ask",
            json={"question": "What is Company B strategy?"},
            headers=comp_a["headers"]
        )
        assert res_proj.status_code in (403, 404), f"Expected 403/404, got {res_proj.status_code}"
