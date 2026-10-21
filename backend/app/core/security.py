import hashlib
import base64

import re
from app.core.runtime import IS_WORKERS

# bcrypt context — cost factor 12 is appropriate for production
# bcrypt has a hard 72-byte limit; we pre-hash with SHA-256 + base64 to avoid
# silent truncation on very long passwords (industry-standard technique).


def _prehash(plain_password: str) -> str:
    """SHA-256 + base64 encode so bcrypt never sees more than 44 bytes."""
    digest = hashlib.sha256(plain_password.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("utf-8")


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password. Never store the plain version."""
    if IS_WORKERS:
        return _database_bcrypt(_prehash(plain_password))
    import bcrypt
    return bcrypt.hashpw(_prehash(plain_password).encode("ascii"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if the plain password matches the stored hash."""
    if IS_WORKERS:
        if not re.fullmatch(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}", hashed_password):
            return False
        # pgcrypto implements bcrypt 2a. MeetVault always prehashes to ASCII
        # base64 (44 bytes), so 2a/2b/2y have identical semantics here. Only the
        # prefix is normalized for comparison; stored hashes are never changed.
        salt = "$2a$" + hashed_password[4:]
        import hmac
        return hmac.compare_digest(_database_bcrypt(_prehash(plain_password), salt), salt)
    import bcrypt
    try:
        return bcrypt.checkpw(_prehash(plain_password).encode("ascii"), hashed_password.encode("ascii"))
    except (ValueError, UnicodeError):
        return False


def _database_bcrypt(prehashed_password: str, salt: str | None = None) -> str:
    """Run costly bcrypt in existing PostgreSQL rather than Worker CPU.

    Requires pgcrypto, already installed in MeetVault's extensions schema.
    This adds no public SQL/RPC function and never stores a plaintext password.
    """
    from sqlalchemy import text
    from app.core.config import settings
    from app.db.session import SessionLocal

    schema = settings.PASSWORD_HASH_SCHEMA
    if schema not in {"extensions", "public"}:
        raise RuntimeError("Unsupported pgcrypto schema")
    if salt is None:
        sql = f'SELECT "{schema}".crypt(:password, "{schema}".gen_salt(\'bf\', 12))'
        parameters = {"password": prehashed_password}
    else:
        sql = f'SELECT "{schema}".crypt(:password, :salt)'
        parameters = {"password": prehashed_password, "salt": salt}
    with SessionLocal() as db:
        return db.execute(text(sql), parameters).scalar_one()

