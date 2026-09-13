from app.api.v1 import auth as auth_router
from app.core.config import Settings


def test_production_cors_accepts_json_array():
    settings = Settings(
        ENVIRONMENT="production",
        BACKEND_CORS_ORIGINS='["https://ai-meet-f8fd0.web.app","https://ai-meet-f8fd0.firebaseapp.com"]',
    )

    assert settings.cors_origins == [
        "https://ai-meet-f8fd0.web.app",
        "https://ai-meet-f8fd0.firebaseapp.com",
    ]


def test_production_cors_accepts_loose_comma_list_with_brackets():
    settings = Settings(
        ENVIRONMENT="production",
        BACKEND_CORS_ORIGINS="[https://ai-meet-f8fd0.web.app,https://ai-meet-f8fd0.firebaseapp.com]",
    )

    assert settings.cors_origins == [
        "https://ai-meet-f8fd0.web.app",
        "https://ai-meet-f8fd0.firebaseapp.com",
    ]


def test_google_auth_exchange_creates_meetvault_user(client, monkeypatch):
    def fake_verify_firebase_id_token(_id_token):
        return {
            "email": "google.user@example.com",
            "email_verified": True,
            "name": "Google User",
            "firebase": {"sign_in_provider": "google.com"},
        }

    monkeypatch.setattr(auth_router, "verify_firebase_id_token", fake_verify_firebase_id_token)

    token_response = client.post(
        "/api/v1/auth/firebase/google",
        json={"id_token": "valid.firebase.token"},
    )

    assert token_response.status_code == 200
    access_token = token_response.json()["access_token"]
    me_response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert me_response.status_code == 200
    assert me_response.json()["email"] == "google.user@example.com"
    assert me_response.json()["full_name"] == "Google User"
    assert me_response.json()["account_type"] == "personal"
