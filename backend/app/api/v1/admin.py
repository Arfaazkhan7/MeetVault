from fastapi import APIRouter, Depends, HTTPException, status
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
    """Dependency enforcing System Admin privileges strictly based on database role."""
    if getattr(current_user, "account_type", "") == "admin":
        return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Requires System Admin privileges",
    )


@router.post("/login", response_model=TokenResponse)
def admin_login(payload: AdminLoginRequest, db: Session = Depends(get_db)):
    """System Admin login endpoint. Authenticates and strictly verifies admin role in database."""
    user = authenticate_user(db, payload.email, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin credentials",
        )

    # Strictly enforce admin privilege check using database account_type
    if getattr(user, "account_type", "") != "admin":
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
