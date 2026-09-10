"""Phase 2 Authentication Tests - test DB provided by conftest.py"""


class TestRegister:
    def test_register_success(self, client):
        res = client.post("/api/v1/auth/register", json={
            "full_name": "Alice Example",
            "email": "alice@example.com",
            "password": "StrongPass1",
        })
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["email"] == "alice@example.com"
        assert body["public_id"].startswith("USR-")
        assert "password" not in body
        assert "hashed_password" not in body

    def test_register_duplicate_email(self, client):
        payload = {"full_name": "Bob", "email": "bob@example.com", "password": "StrongPass1"}
        r1 = client.post("/api/v1/auth/register", json=payload)
        assert r1.status_code == 201
        r2 = client.post("/api/v1/auth/register", json=payload)
        assert r2.status_code == 409

    def test_register_invalid_email(self, client):
        res = client.post("/api/v1/auth/register", json={
            "full_name": "Carol", "email": "not-an-email", "password": "StrongPass1",
        })
        assert res.status_code == 422

    def test_register_weak_password_too_short(self, client):
        res = client.post("/api/v1/auth/register", json={
            "full_name": "Dan", "email": "dan@example.com", "password": "abc",
        })
        assert res.status_code == 422

    def test_register_weak_password_no_uppercase(self, client):
        res = client.post("/api/v1/auth/register", json={
            "full_name": "Eve", "email": "eve@example.com", "password": "alllowercase1",
        })
        assert res.status_code == 422

    def test_register_weak_password_no_digit(self, client):
        res = client.post("/api/v1/auth/register", json={
            "full_name": "Frank", "email": "frank@example.com", "password": "NoDigitHere",
        })
        assert res.status_code == 422

    def test_register_blank_name(self, client):
        res = client.post("/api/v1/auth/register", json={
            "full_name": "   ", "email": "grace@example.com", "password": "StrongPass1",
        })
        assert res.status_code == 422


class TestLogin:
    def _register(self, client, email="user@example.com", password="StrongPass1"):
        r = client.post("/api/v1/auth/register", json={
            "full_name": "Test User", "email": email, "password": password,
        })
        assert r.status_code == 201, r.text

    def test_login_success(self, client):
        self._register(client)
        res = client.post("/api/v1/auth/login", json={
            "email": "user@example.com", "password": "StrongPass1",
        })
        assert res.status_code == 200, res.text
        body = res.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["token_type"] == "bearer"

    def test_login_wrong_password(self, client):
        self._register(client)
        res = client.post("/api/v1/auth/login", json={
            "email": "user@example.com", "password": "WrongPass1",
        })
        assert res.status_code == 401

    def test_login_unknown_email(self, client):
        res = client.post("/api/v1/auth/login", json={
            "email": "nobody@example.com", "password": "StrongPass1",
        })
        assert res.status_code == 401

    def test_login_case_insensitive_email(self, client):
        self._register(client, email="user@example.com")
        res = client.post("/api/v1/auth/login", json={
            "email": "USER@EXAMPLE.COM", "password": "StrongPass1",
        })
        assert res.status_code == 200


class TestTokenAndMe:
    def _get_tokens(self, client):
        client.post("/api/v1/auth/register", json={
            "full_name": "Test User", "email": "user@example.com", "password": "StrongPass1",
        })
        res = client.post("/api/v1/auth/login", json={
            "email": "user@example.com", "password": "StrongPass1",
        })
        assert res.status_code == 200, res.text
        return res.json()

    def test_me_with_valid_token(self, client):
        tokens = self._get_tokens(client)
        res = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["email"] == "user@example.com"

    def test_me_without_token(self, client):
        res = client.get("/api/v1/auth/me")
        assert res.status_code == 401

    def test_me_with_invalid_token(self, client):
        res = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer totally.invalid.token"},
        )
        assert res.status_code == 401

    def test_refresh_success(self, client):
        tokens = self._get_tokens(client)
        res = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert res.status_code == 200, res.text
        new_tokens = res.json()
        assert "access_token" in new_tokens
        me_res = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
        )
        assert me_res.status_code == 200

    def test_refresh_with_access_token_rejected(self, client):
        tokens = self._get_tokens(client)
        res = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]})
        assert res.status_code == 401

    def test_logout_success(self, client):
        tokens = self._get_tokens(client)
        res = client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert res.status_code == 200

    def test_logout_without_token(self, client):
        res = client.post("/api/v1/auth/logout")
        assert res.status_code == 401


class TestPasswordSecurity:
    def test_password_not_in_register_response(self, client):
        res = client.post("/api/v1/auth/register", json={
            "full_name": "Secure User", "email": "sec@example.com", "password": "StrongPass1",
        })
        assert res.status_code == 201, res.text
        assert "StrongPass1" not in res.text
        assert "hashed_password" not in res.text

    def test_password_not_in_me_response(self, client):
        client.post("/api/v1/auth/register", json={
            "full_name": "Secure User", "email": "sec@example.com", "password": "StrongPass1",
        })
        login = client.post("/api/v1/auth/login", json={
            "email": "sec@example.com", "password": "StrongPass1",
        })
        token = login.json()["access_token"]
        res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200, res.text
        assert "hashed_password" not in res.text
        assert "StrongPass1" not in res.text
