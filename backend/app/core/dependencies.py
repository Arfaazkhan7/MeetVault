from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.tokens import decode_token, JWTError
from app.core.roles import Role, role_gte, ProjectRole, project_role_gte
from app.db.session import get_db
from app.services.user_service import get_user_by_public_id
from app.models.user import User
from app.models.company import CompanyMember
from app.models.project import Project, ProjectMember
from app.core.config import settings

_bearer = HTTPBearer(auto_error=False)
_bearer_optional = HTTPBearer(auto_error=False)

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise credentials_exception
    token = credentials.credentials.strip()

    # Handle local / fallback tokens containing user email (e.g. mv-local-token:user@gmail.com)
    # Strictly prohibited in production/staging environments
    if settings.ENVIRONMENT.lower() not in ("production", "prod", "staging") and (token.startswith("mv-local-") or token.startswith("mail-")):
        email = None
        if ":" in token:
            email = token.split(":", 1)[1].strip()
        elif "-" in token:
            parts = token.split("-")
            for p in parts:
                if "@" in p:
                    email = p.strip()
                    break
        if email and "@" in email:
            from app.services.user_service import get_or_create_firebase_personal_user
            return get_or_create_firebase_personal_user(db, email=email, full_name=None)

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


def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_optional),
    db: Session = Depends(get_db),
) -> User | None:
    if not credentials or not credentials.credentials:
        return None
    token = credentials.credentials.strip()

    # Strictly prohibited in production/staging environments
    if settings.ENVIRONMENT.lower() not in ("production", "prod", "staging") and (token.startswith("mv-local-") or token.startswith("mail-")):
        email = None
        if ":" in token:
            email = token.split(":", 1)[1].strip()
        elif "-" in token:
            parts = token.split("-")
            for p in parts:
                if "@" in p:
                    email = p.strip()
                    break
        if email and "@" in email:
            from app.services.user_service import get_or_create_firebase_personal_user
            return get_or_create_firebase_personal_user(db, email=email, full_name=None)

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None
        public_id: str = payload.get("sub")
        if not public_id:
            return None
        user = get_user_by_public_id(db, public_id)
        if user and user.deleted_at is None:
            return user
        return None
    except JWTError:
        return None


def get_membership(db: Session, user_public_id: str, company_public_id: str) -> CompanyMember:
    membership = (
        db.query(CompanyMember)
        .filter(
            CompanyMember.user_id == user_public_id,
            CompanyMember.company_id == company_public_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this company",
        )
    return membership


def require_role(minimum_role: Role):
    def _dependency(
        company_id: str,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> CompanyMember:
        membership = get_membership(db, current_user.public_id, company_id)
        if not role_gte(Role(membership.role), minimum_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role {minimum_role.value} or higher",
            )
        return membership
    return _dependency


def get_project_and_authorize(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project:
    """
    Fetch project by ID, ensure user is a member of its company.
    Also returns the project.
    """
    project = db.query(Project).filter(Project.public_id == project_id, Project.deleted_at.is_(None)).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # Must be member of the company to access any project within it
    get_membership(db, current_user.public_id, project.company_id)
    return project

def require_project_admin(
    project: Project = Depends(get_project_and_authorize),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project:
    """
    Ensure user has Company Admin/Project Manager role OR is a Project Admin.
    """
    # 1. Company-level override
    company_membership = get_membership(db, current_user.public_id, project.company_id)
    if role_gte(Role(company_membership.role), Role.PROJECT_MANAGER):
        return project

    # 2. Project-level membership
    project_member = db.query(ProjectMember).filter(
        ProjectMember.project_id == project.public_id,
        ProjectMember.user_id == current_user.public_id
    ).first()

    if not project_member or not project_role_gte(ProjectRole(project_member.role), ProjectRole.ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires project admin privileges")

    return project

def require_maintenance_or_admin(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    """
    Enforces administrator authorization for system maintenance and orphan audio cleanup.
    Allowed callers:
    1. System Administrator (account_type == 'admin').
    2. Company Administrator (CompanyMember with role COMPANY_ADMIN or SUPER_ADMIN).
    Standard members (MEMBER, PERSONAL_USER) are rejected with 403 Forbidden.
    """
    is_sys_admin = getattr(current_user, "account_type", "") == "admin"
    if is_sys_admin:
        return current_user

    # Check if the user is a Company Admin in any active company
    membership = (
        db.query(CompanyMember)
        .filter(
            CompanyMember.user_id == current_user.public_id,
            CompanyMember.role.in_([Role.COMPANY_ADMIN.value, Role.SUPER_ADMIN.value]),
        )
        .first()
    )
    if membership:
        return current_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Requires system admin or company admin privileges to reconcile audio cleanup",
    )
