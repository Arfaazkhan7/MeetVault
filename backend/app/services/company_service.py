from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.company import Company, CompanyMember
from app.models.user import User
from app.core.roles import Role


# ── ID generation ─────────────────────────────────────────────────────────
def _next_company_id(db: Session) -> str:
    count = db.query(Company).count() + 1
    return f"COMP-{count:04d}"


# ── Company CRUD ──────────────────────────────────────────────────────────
def create_company(db: Session, name: str, domain: str | None, creator: User) -> Company:
    """Create a company and make the creator its COMPANY_ADMIN."""
    company = Company(
        public_id=_next_company_id(db),
        name=name.strip(),
        domain=domain.strip() if domain else None,
    )
    db.add(company)
    db.flush()   # populate company.public_id without committing

    membership = CompanyMember(
        user_id=creator.public_id,
        company_id=company.public_id,
        role=Role.COMPANY_ADMIN.value,
    )
    db.add(membership)
    db.commit()
    db.refresh(company)
    return company


def get_company_or_404(db: Session, company_public_id: str) -> Company:
    company = (
        db.query(Company)
        .filter(Company.public_id == company_public_id, Company.deleted_at.is_(None))
        .first()
    )
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return company


def list_user_companies(db: Session, user_public_id: str) -> list[Company]:
    memberships = (
        db.query(CompanyMember)
        .filter(CompanyMember.user_id == user_public_id)
        .all()
    )
    company_ids = [m.company_id for m in memberships]
    return (
        db.query(Company)
        .filter(Company.public_id.in_(company_ids), Company.deleted_at.is_(None))
        .all()
    )


# ── Member CRUD ───────────────────────────────────────────────────────────
def add_member(
    db: Session,
    company_public_id: str,
    user: User,
    role: Role,
    department: str | None,
    job_title: str | None,
) -> CompanyMember:
    existing = (
        db.query(CompanyMember)
        .filter(
            CompanyMember.user_id == user.public_id,
            CompanyMember.company_id == company_public_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this company",
        )
    member = CompanyMember(
        user_id=user.public_id,
        company_id=company_public_id,
        role=role.value,
        department=department,
        job_title=job_title,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def update_member(
    db: Session,
    company_public_id: str,
    target_user_public_id: str,
    role: Role | None,
    department: str | None,
    job_title: str | None,
) -> CompanyMember:
    member = (
        db.query(CompanyMember)
        .filter(
            CompanyMember.user_id == target_user_public_id,
            CompanyMember.company_id == company_public_id,
        )
        .first()
    )
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    if role is not None:
        member.role = role.value
    if department is not None:
        member.department = department
    if job_title is not None:
        member.job_title = job_title
    db.commit()
    db.refresh(member)
    return member


def remove_member(db: Session, company_public_id: str, target_user_public_id: str, requester_public_id: str) -> None:
    if target_user_public_id == requester_public_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove yourself",
        )
    member = (
        db.query(CompanyMember)
        .filter(
            CompanyMember.user_id == target_user_public_id,
            CompanyMember.company_id == company_public_id,
        )
        .first()
    )
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    db.delete(member)
    db.commit()


def list_members_with_users(db: Session, company_public_id: str) -> list[dict]:
    """Return member list with user details joined in Python (SQLite-safe)."""
    memberships = (
        db.query(CompanyMember)
        .filter(CompanyMember.company_id == company_public_id)
        .all()
    )
    user_ids = [m.user_id for m in memberships]
    users = db.query(User).filter(User.public_id.in_(user_ids)).all()
    user_map = {u.public_id: u for u in users}

    result = []
    for m in memberships:
        u = user_map.get(m.user_id)
        if u:
            result.append({
                "user_public_id": u.public_id,
                "email": u.email,
                "full_name": u.full_name,
                "role": m.role,
                "department": m.department,
                "job_title": m.job_title,
            })
    return result
