from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.tokens import create_token, decode_token
from app.core.dependencies import get_current_user
from app.services.user_service import (
    create_user,
    authenticate_user,
    authenticate_personal_user,
    authenticate_workspace_user,
    get_or_create_firebase_personal_user,
)
from app.services.firebase_auth_service import verify_firebase_id_token
from app.schemas.auth import (
    RegisterRequest,
    LoginRequest,
    PersonalLoginRequest,
    WorkspaceLoginRequest,
    FirebaseLoginRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
    MeResponse,
)
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user. Returns user info (never the password)."""
    try:
        user = create_user(
            db=db,
            full_name=payload.full_name,
            email=payload.email,
            plain_password=payload.password,
            organization_name=payload.organization_name,
            account_type=payload.account_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return user


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Standard authentication. Returns access + refresh tokens."""
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


@router.post("/login/personal", response_model=TokenResponse)
def login_personal(payload: PersonalLoginRequest, db: Session = Depends(get_db)):
    """
    Personal mode login: Email + Password.
    No Workspace ID required.
    """
    user = authenticate_personal_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_token(subject=user.public_id, token_type="access")
    refresh_token = create_token(subject=user.public_id, token_type="refresh")
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login/workspace", response_model=TokenResponse)
def login_workspace(payload: WorkspaceLoginRequest, db: Session = Depends(get_db)):
    """
    Workspace mode login: Workspace ID + Email + Password.
    Backend verifies workspace existence, user credentials, and active workspace membership.
    """
    auth_result = authenticate_workspace_user(
        db,
        workspace_code=payload.workspace_code,
        email=payload.email,
        plain_password=payload.password,
    )
    if not auth_result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid workspace code, email, password, or inactive workspace membership",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user, company = auth_result
    access_token = create_token(subject=user.public_id, token_type="access")
    refresh_token = create_token(subject=user.public_id, token_type="refresh")
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        workspace_id=company.public_id,
    )


@router.post("/firebase/google", response_model=TokenResponse)
def login_with_google(payload: FirebaseLoginRequest, db: Session = Depends(get_db)):
    """
    Exchange a verified Firebase Google identity for MeetVault tokens.
    MeetVault remains the authority for roles, workspace membership, and access.
    """
    try:
        decoded = verify_firebase_id_token(payload.id_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Firebase authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    firebase_uid = decoded.get("uid") or decoded.get("sub")
    email = decoded.get("email")
    email_verified = decoded.get("email_verified", False)
    if not email or not email_verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google account email must be verified",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_or_create_firebase_personal_user(
        db=db,
        email=email,
        full_name=decoded.get("name"),
        firebase_uid=firebase_uid,
    )
    access_token = create_token(subject=user.public_id, token_type="access")
    refresh_token = create_token(subject=user.public_id, token_type="refresh")
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        public_id=user.public_id,
        user=UserResponse.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(payload: RefreshRequest):
    """
    Exchange a valid refresh token for a new access + refresh token pair.
    Old refresh token is implicitly discarded (stateless rotation).
    """
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
    """Stateless logout — client must discard tokens locally."""
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=MeResponse)
def me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return current_user
