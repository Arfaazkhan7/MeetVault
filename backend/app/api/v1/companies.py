from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.roles import Role
from app.models.user import User
from app.schemas.company import (
    CreateCompanyRequest,
    CompanyResponse,
    AddMemberRequest,
    UpdateMemberRoleRequest,
    MemberResponse,
)
from app.services.company_service import (
    create_company,
    get_company_or_404,
    list_user_companies,
    add_member,
    update_member,
    remove_member,
    list_members_with_users,
)
from app.services.user_service import get_user_by_email

router = APIRouter(prefix="/companies", tags=["companies"])


# ── Company endpoints ─────────────────────────────────────────────────────

@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
def create_new_company(
    payload: CreateCompanyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Any authenticated user can create a company. They become its COMPANY_ADMIN."""
    return create_company(db, payload.name, payload.domain, current_user)


@router.get("", response_model=list[CompanyResponse])
def my_companies(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all companies the current user is a member of."""
    return list_user_companies(db, current_user.public_id)


@router.get("/{company_id}", response_model=CompanyResponse)
def get_company(
    company_id: str,
    membership=Depends(require_role(Role.MEMBER)),
    db: Session = Depends(get_db),
):
    """Get company details. Any member may view."""
    return get_company_or_404(db, company_id)


# ── Member endpoints ──────────────────────────────────────────────────────

@router.get("/{company_id}/members", response_model=list[MemberResponse])
def list_members(
    company_id: str,
    membership=Depends(require_role(Role.MEMBER)),
    db: Session = Depends(get_db),
):
    """List all members of the company. Any member may view."""
    return list_members_with_users(db, company_id)


@router.post(
    "/{company_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_company_member(
    company_id: str,
    payload: AddMemberRequest,
    membership=Depends(require_role(Role.COMPANY_ADMIN)),
    db: Session = Depends(get_db),
):
    """Add a user to the company by email. Requires COMPANY_ADMIN or higher."""
    target_user = get_user_by_email(db, payload.email)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    member = add_member(db, company_id, target_user, payload.role, payload.department, payload.job_title)
    return {
        "user_public_id": target_user.public_id,
        "email": target_user.email,
        "full_name": target_user.full_name,
        "role": member.role,
        "department": member.department,
        "job_title": member.job_title,
    }


@router.patch("/{company_id}/members/{user_public_id}", response_model=MemberResponse)
def update_member_role(
    company_id: str,
    user_public_id: str,
    payload: UpdateMemberRoleRequest,
    membership=Depends(require_role(Role.COMPANY_ADMIN)),
    db: Session = Depends(get_db),
):
    """Update a member's role. Requires COMPANY_ADMIN or higher."""
    from app.services.user_service import get_user_by_public_id
    target_user = get_user_by_public_id(db, user_public_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    member = update_member(db, company_id, user_public_id, payload.role, payload.department, payload.job_title)
    return {
        "user_public_id": target_user.public_id,
        "email": target_user.email,
        "full_name": target_user.full_name,
        "role": member.role,
        "department": member.department,
        "job_title": member.job_title,
    }


@router.delete("/{company_id}/members/{user_public_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_company_member(
    company_id: str,
    user_public_id: str,
    current_user: User = Depends(get_current_user),
    membership=Depends(require_role(Role.COMPANY_ADMIN)),
    db: Session = Depends(get_db),
):
    """Remove a member. Requires COMPANY_ADMIN. Cannot remove self."""
    remove_member(db, company_id, user_public_id, current_user.public_id)
