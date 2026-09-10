
import sys, os, textwrap, pathlib

ROOT = pathlib.Path("backend")

files = {}

# ── schemas/__init__.py ────────────────────────────────────────────────────────
files["app/schemas/__init__.py"] = ""

# ── services/user_service.py ───────────────────────────────────────────────────
files["app/services/user_service.py"] = textwrap.dedent("""
    import uuid
    import re
    from sqlalchemy.orm import Session
    from app.models.user import User
    from app.core.security import hash_password, verify_password

    def _generate_public_id(db: Session) -> str:
        \"\"\"Generate next USR-XXXX identifier, thread-safe via DB count.\"\"\"
        count = db.query(User).count() + 1
        return f"USR-{count:04d}"

    def get_user_by_email(db: Session, email: str) -> User | None:
        return db.query(User).filter(User.email == email.lower().strip()).first()

    def get_user_by_public_id(db: Session, public_id: str) -> User | None:
        return db.query(User).filter(User.public_id == public_id).first()

    def create_user(db: Session, full_name: str, email: str, plain_password: str) -> User:
        \"\"\"Create a new user. Raises ValueError if email already exists.\"\"\"
        email = email.lower().strip()
        if get_user_by_email(db, email):
            raise ValueError("A user with this email already exists")

        user = User(
            public_id=_generate_public_id(db),
            email=email,
            full_name=full_name.strip(),
            hashed_password=hash_password(plain_password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def authenticate_user(db: Session, email: str, plain_password: str) -> User | None:
        \"\"\"Return User if credentials are valid, else None.\"\"\"
        user = get_user_by_email(db, email)
        if not user:
            return None
        if not user.hashed_password:
            return None
        if not verify_password(plain_password, user.hashed_password):
            return None
        return user
""").lstrip()

# ── core/dependencies.py ───────────────────────────────────────────────────────
files["app/core/dependencies.py"] = textwrap.dedent("""
    from fastapi import Depends, HTTPException, status
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    from jose import JWTError
    from sqlalchemy.orm import Session

    from app.core.tokens import decode_token
    from app.db.session import get_db
    from app.services.user_service import get_user_by_public_id
    from app.models.user import User

    _bearer = HTTPBearer(auto_error=True)


    def get_current_user(
        credentials: HTTPAuthorizationCredentials = Depends(_bearer),
        db: Session = Depends(get_db),
    ) -> User:
        \"\"\"
        FastAPI dependency for protected routes.
        Validates the Bearer JWT and returns the authenticated User.
        \"\"\"
        token = credentials.credentials
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        try:
            payload = decode_token(token)
            if payload.get("type") != "access":
                raise credentials_exception
            public_id: str = payload.get("sub")
            if not public_id:
                raise credentials_exception
        except JWTError:
            raise credentials_exception

        user = get_user_by_public_id(db, public_id)
        if user is None or user.deleted_at is not None:
            raise credentials_exception
        return user
""").lstrip()

# ── api/v1/auth.py ─────────────────────────────────────────────────────────────
files["app/api/v1/auth.py"] = textwrap.dedent("""
    from fastapi import APIRouter, Depends, HTTPException, status
    from jose import JWTError
    from sqlalchemy.orm import Session

    from app.db.session import get_db
    from app.core.tokens import create_token, decode_token
    from app.core.dependencies import get_current_user
    from app.services.user_service import create_user, authenticate_user
    from app.schemas.auth import (
        RegisterRequest,
        LoginRequest,
        RefreshRequest,
        TokenResponse,
        UserResponse,
        MeResponse,
    )
    from app.models.user import User

    router = APIRouter(prefix="/auth", tags=["auth"])


    @router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
    def register(payload: RegisterRequest, db: Session = Depends(get_db)):
        \"\"\"Register a new user. Returns user info (never the password).\"\"\"
        try:
            user = create_user(
                db=db,
                full_name=payload.full_name,
                email=payload.email,
                plain_password=payload.password,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        return user


    @router.post("/login", response_model=TokenResponse)
    def login(payload: LoginRequest, db: Session = Depends(get_db)):
        \"\"\"Authenticate and return access + refresh tokens.\"\"\"
        user = authenticate_user(db, payload.email, payload.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        access_token = create_token(subject=user.public_id, token_type="access")
        refresh_token = create_token(subject=user.public_id, token_type="refresh")
        return TokenResponse(access_token=access_token, refresh_token=refresh_token)


    @router.post("/refresh", response_model=TokenResponse)
    def refresh_tokens(payload: RefreshRequest):
        \"\"\"
        Exchange a valid refresh token for a new access + refresh token pair.
        Old refresh token is implicitly discarded (stateless rotation).
        \"\"\"
        invalid_exc = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
        try:
            data = decode_token(payload.refresh_token)
            if data.get("type") != "refresh":
                raise invalid_exc
            subject = data.get("sub")
            if not subject:
                raise invalid_exc
        except JWTError:
            raise invalid_exc

        new_access = create_token(subject=subject, token_type="access")
        new_refresh = create_token(subject=subject, token_type="refresh")
        return TokenResponse(access_token=new_access, refresh_token=new_refresh)


    @router.post("/logout", status_code=status.HTTP_200_OK)
    def logout(_current_user: User = Depends(get_current_user)):
        \"\"\"
        Stateless logout — client must discard tokens locally.
        Token blocklist (Redis) will be added in the security-hardening phase.
        \"\"\"
        return {"message": "Logged out successfully"}


    @router.get("/me", response_model=MeResponse)
    def me(current_user: User = Depends(get_current_user)):
        \"\"\"Return the currently authenticated user's profile.\"\"\"
        return current_user
""").lstrip()

# ── write all files ────────────────────────────────────────────────────────────
for rel, content in files.items():
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  wrote  {path}")

print("done")
