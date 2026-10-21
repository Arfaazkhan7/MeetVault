"""Migration boundaries that must stay compatible with the existing API."""
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import JWTError, jwt

from app.core.config import settings
from app.core.security import hash_password, verify_password, _prehash
from app.services.firebase_auth_service import _verify_portable_firebase_token


@pytest.fixture
def firebase_signer(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(
        200, json={"test-key": public}, request=httpx.Request("GET", "https://example.invalid"),
    ))
    def sign(**changes):
        now = int(time.time())
        claims = {"sub": "firebase-user", "aud": settings.FIREBASE_PROJECT_ID,
                  "iss": f"https://securetoken.google.com/{settings.FIREBASE_PROJECT_ID}",
                  "iat": now - 1, "auth_time": now - 10, "exp": now + 60,
                  "email": "verified@example.com", "email_verified": True}
        claims.update(changes)
        return jwt.encode(claims, private, algorithm="RS256", headers={"kid": "test-key"})
    return sign


def test_portable_firebase_signature(firebase_signer):
    assert _verify_portable_firebase_token(firebase_signer())["uid"] == "firebase-user"


@pytest.mark.parametrize("changes", [
    {"aud": "other-project"}, {"iss": "https://attacker.invalid"},
    {"exp": 1}, {"iat": 9999999999}, {"auth_time": 9999999999},
    {"sub": ""}, {"sub": "x" * 129}, {"auth_time": "invalid"},
])
def test_portable_firebase_rejects_bad_claims(firebase_signer, changes):
    with pytest.raises(JWTError):
        _verify_portable_firebase_token(firebase_signer(**changes))


def test_password_hash_matches_existing_prehash_format():
    import bcrypt
    existing = bcrypt.hashpw(_prehash("a" * 150).encode(), bcrypt.gensalt(rounds=4)).decode()
    assert verify_password("a" * 150, existing)
    assert not verify_password("a" * 149, existing)
    assert not verify_password("password", "invalid-hash")


def test_workers_password_verification_offloads_without_rehashing_in_worker(monkeypatch):
    from app.core import security
    monkeypatch.setattr(security, "IS_WORKERS", True)
    stored = "$2b$12$" + "a" * 53
    normalized = "$2a$" + stored[4:]
    crypt = Mock(return_value=normalized)
    monkeypatch.setattr(security, "_database_bcrypt", crypt)
    assert security.verify_password("existing-password", stored)
    crypt.assert_called_once_with(security._prehash("existing-password"), normalized)
    crypt.return_value = "$2a$12$" + "b" * 53
    assert not security.verify_password("wrong-password", stored)


def test_production_rejects_local_email_tokens(client, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer mv-local-token:anyone@example.com"})
    assert response.status_code == 401


def test_hyperdrive_uses_request_binding_without_cached_sockets(monkeypatch):
    import pg8000.dbapi
    from app.db.session import _worker_connect
    binding = SimpleNamespace(host="localhost", port="5432", user="test", password="test", database="test")
    monkeypatch.setitem(sys.modules, "workers", SimpleNamespace(env=SimpleNamespace(HYPERDRIVE=binding)))
    connect = Mock(return_value=object())
    monkeypatch.setattr(pg8000.dbapi, "connect", connect)
    _worker_connect()
    connect.assert_called_once_with(host="localhost", port=5432, user="test", password="test", database="test", ssl_context=False)


def test_cloud_document_uses_private_object_storage(monkeypatch):
    from app.services.document_service import save_private_file
    from app.services.storage_service import SupabaseStorageService
    monkeypatch.setattr(settings, "DOCUMENT_STORAGE_BACKEND", "supabase")
    upload = Mock()
    monkeypatch.setattr(SupabaseStorageService, "upload_private_file", upload)
    location = save_private_file("COMP-1", "doc_test", "notes.pdf", b"private")
    assert location == f"supabase://{settings.SUPABASE_DOCUMENTS_BUCKET}/COMP-1/doc_test.pdf"
    upload.assert_called_once_with(path="COMP-1/doc_test.pdf", content=b"private", content_type="application/octet-stream")
