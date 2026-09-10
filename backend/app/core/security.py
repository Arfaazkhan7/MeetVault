import hashlib
import base64

from passlib.context import CryptContext

# bcrypt context — cost factor 12 is appropriate for production
# bcrypt has a hard 72-byte limit; we pre-hash with SHA-256 + base64 to avoid
# silent truncation on very long passwords (industry-standard technique).
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


def _prehash(plain_password: str) -> str:
    """SHA-256 + base64 encode so bcrypt never sees more than 44 bytes."""
    digest = hashlib.sha256(plain_password.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("utf-8")


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password. Never store the plain version."""
    return _pwd_context.hash(_prehash(plain_password))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if the plain password matches the stored hash."""
    return _pwd_context.verify(_prehash(plain_password), hashed_password)
