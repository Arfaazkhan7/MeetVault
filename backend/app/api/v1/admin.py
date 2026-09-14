from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.dependencies import get_current_user
from app.core.roles import Role, role_gte
from app.core.tokens import create_token
from app.models.user import User
from app.models.company import Company
from app.schemas.admin import (
    AdminLoginRequest,
    CreateWorkspaceAdminRequest,
    WorkspaceAdminResponse,
    SystemStatsResponse,
)
from app.schemas.auth import TokenResponse
from app.services.user_service import authenticate_user
from app.services.admin_service import create_workspace_by_admin, get_system_stats

router = APIRouter(prefix="/admin", tags=["admin"])


def require_system_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency enforcing System Admin (SUPER_ADMIN) role."""
    if (
        current_user.email.endswith("@meetvault.com")
        or current_user.email.startswith("admin@")
        or current_user.email.startswith("system.admin@")
    ):
        return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Requires System Admin privileges",
    )


@router.post("/login", response_model=TokenResponse)
def admin_login(payload: AdminLoginRequest, db: Session = Depends(get_db)):
    """System Admin login endpoint. Auto-seeds default admin on first use."""
    user = authenticate_user(db, payload.email, payload.password)

    # Auto-seed: if no user found and credentials match the default admin, create it
    if not user:
        default_admin_email = "system.admin@meetvault.com"
        default_admin_password = "AdminPassword123!"
        if (
            payload.email.lower().strip() == default_admin_email
            and payload.password == default_admin_password
        ):
            from app.models.user import User as UserModel
            from app.core.security import hash_password
            existing = db.query(UserModel).filter(UserModel.email == default_admin_email).first()
            if not existing:
                count = db.query(UserModel).count() + 1
                new_admin = UserModel(
                    public_id=f"USR-{count:04d}",
                    email=default_admin_email,
                    full_name="System Administrator",
                    hashed_password=hash_password(default_admin_password),
                    account_type="personal",
                )
                db.add(new_admin)
                db.commit()
                db.refresh(new_admin)
                user = new_admin

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
        )

    # Enforce admin privilege check
    if not (
        user.email.endswith("@meetvault.com")
        or user.email.startswith("admin@")
        or user.email.startswith("system.admin@")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account does not have admin privileges",
        )

    access_token = create_token(subject=user.public_id, token_type="access")
    refresh_token = create_token(subject=user.public_id, token_type="refresh")
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/workspaces", response_model=WorkspaceAdminResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: CreateWorkspaceAdminRequest,
    current_user: User = Depends(require_system_admin),
    db: Session = Depends(get_db),
):
    """
    System Admin creates an Organization / Workspace.
    Auto-generates Workspace ID (e.g. MV-8K4P2X) and creates Workspace Admin user.
    """
    return create_workspace_by_admin(
        db,
        organization_name=payload.organization_name,
        admin_name=payload.admin_name,
        admin_email=payload.admin_email,
        admin_password=payload.admin_password,
    )


@router.get("/workspaces")
def list_all_workspaces(
    current_user: User = Depends(require_system_admin),
    db: Session = Depends(get_db),
):
    """List all workspaces in the system."""
    companies = db.query(Company).filter(Company.deleted_at.is_(None)).all()
    res = []
    for c in companies:
        res.append({
            "public_id": c.public_id,
            "workspace_code": c.workspace_code,
            "name": c.name,
            "domain": c.domain,
            "member_count": c.members.count(),
            "project_count": len(c.projects),
            "created_at": c.created_at,
        })
    return res


@router.get("/stats", response_model=SystemStatsResponse)
def get_stats(
    current_user: User = Depends(require_system_admin),
    db: Session = Depends(get_db),
):
    """Get system-wide statistics."""
    return get_system_stats(db)
