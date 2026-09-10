from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from pydantic import EmailStr
import secrets
import string

from app.models.company import Company, CompanyMember
from app.models.user import User
from app.models.project import Project
from app.models.meeting import Meeting
from app.models.recording import MeetingRecording
from app.core.security import hash_password
from app.core.roles import Role
from app.services.company_service import _next_company_id
from app.services.project_service import create_project


def _generate_workspace_code(db: Session) -> str:
    """Generate a clean, readable workspace code (e.g., MV-8K4P2X)."""
    alphabet = string.ascii_uppercase + string.digits
    alphabet = ''.join(c for c in alphabet if c not in '0O1I8B')
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(6))
        ws_code = f"MV-{code}"
        existing = db.query(Company).filter(
            (Company.workspace_code == ws_code) | (Company.public_id == ws_code)
        ).first()
        if not existing:
            return ws_code


def create_workspace_by_admin(
    db: Session,
    organization_name: str,
    admin_name: str,
    admin_email: EmailStr | str,
    admin_password: str,
) -> dict:
    """
    System Admin creates a Workspace:
    1. Generates auto workspace_code (e.g., MV-8K4P2X)
    2. Creates Company record
    3. Provisions or fetches Workspace Admin user
    4. Grants COMPANY_ADMIN membership
    5. Auto-creates default project 'General'
    """
    admin_email_str = str(admin_email).lower().strip()
    ws_code = _generate_workspace_code(db)
    comp_id = _next_company_id(db)

    company = Company(
        public_id=comp_id,
        workspace_code=ws_code,
        name=organization_name.strip(),
    )
    db.add(company)
    db.flush()

    # Find or create admin user
    user = db.query(User).filter(User.email == admin_email_str).first()
    if not user:
        count = db.query(User).count() + 1
        user_public_id = f"USR-{count:04d}"
        user = User(
            public_id=user_public_id,
            email=admin_email_str,
            full_name=admin_name.strip(),
            hashed_password=hash_password(admin_password),
        )
        db.add(user)
        db.flush()

    # Add company membership as COMPANY_ADMIN
    existing_mem = db.query(CompanyMember).filter(
        CompanyMember.user_id == user.public_id,
        CompanyMember.company_id == company.public_id,
    ).first()
    if not existing_mem:
        membership = CompanyMember(
            user_id=user.public_id,
            company_id=company.public_id,
            role=Role.COMPANY_ADMIN.value,
        )
        db.add(membership)

    # Auto-create default project
    create_project(db, company.public_id, "General", "Default project for meetings", user)

    db.commit()
    db.refresh(company)
    db.refresh(user)

    return {
        "workspace_id": company.public_id,
        "workspace_code": company.workspace_code,
        "organization_name": company.name,
        "admin_public_id": user.public_id,
        "admin_email": user.email,
        "admin_name": user.full_name,
        "created_at": company.created_at,
    }


def get_system_stats(db: Session) -> dict:
    return {
        "total_users": db.query(User).count(),
        "total_workspaces": db.query(Company).filter(Company.deleted_at.is_(None)).count(),
        "total_projects": db.query(Project).filter(Project.deleted_at.is_(None)).count(),
        "total_meetings": db.query(Meeting).filter(Meeting.deleted_at.is_(None)).count(),
        "total_recordings": db.query(MeetingRecording).filter(MeetingRecording.deleted_at.is_(None)).count(),
    }
