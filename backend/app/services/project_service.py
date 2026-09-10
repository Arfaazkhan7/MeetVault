from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.project import Project, ProjectMember
from app.models.user import User
from app.core.roles import ProjectRole


def _next_project_id(db: Session) -> str:
    count = db.query(Project).count() + 1
    return f"PRJ-{count:04d}"


def create_project(db: Session, company_id: str, name: str, description: str | None, creator: User) -> Project:
    project = Project(
        public_id=_next_project_id(db),
        company_id=company_id,
        name=name.strip(),
        description=description.strip() if description else None,
    )
    db.add(project)
    db.flush()

    # Creator becomes project admin
    member = ProjectMember(
        user_id=creator.public_id,
        project_id=project.public_id,
        role=ProjectRole.ADMIN.value,
    )
    db.add(member)
    db.commit()
    db.refresh(project)
    return project

def list_projects_for_company(db: Session, company_id: str, status: str = "ACTIVE") -> list[Project]:
    query = db.query(Project).filter(
        Project.company_id == company_id,
        Project.deleted_at.is_(None)
    )
    if status:
        query = query.filter(Project.status == status)
    return query.all()


def list_all_projects_for_user(db: Session, user_public_id: str) -> list[Project]:
    from app.models.company import CompanyMember
    memberships = db.query(CompanyMember).filter(CompanyMember.user_id == user_public_id).all()
    company_ids = [m.company_id for m in memberships]
    if not company_ids:
        return []
    return db.query(Project).filter(
        Project.company_id.in_(company_ids),
        Project.deleted_at.is_(None)
    ).all()

def update_project(db: Session, project: Project, name: str | None, description: str | None) -> Project:
    if name is not None:
        project.name = name.strip()
    if description is not None:
        project.description = description.strip()
    db.commit()
    db.refresh(project)
    return project

def archive_project(db: Session, project: Project) -> Project:
    project.status = "ARCHIVED"
    db.commit()
    db.refresh(project)
    return project

def add_project_member(db: Session, project: Project, user_public_id: str, role: ProjectRole) -> ProjectMember:
    existing = db.query(ProjectMember).filter(
        ProjectMember.user_id == user_public_id,
        ProjectMember.project_id == project.public_id
    ).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already in project")

    member = ProjectMember(
        user_id=user_public_id,
        project_id=project.public_id,
        role=role.value
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member

def remove_project_member(db: Session, project: Project, user_public_id: str) -> None:
    member = db.query(ProjectMember).filter(
        ProjectMember.user_id == user_public_id,
        ProjectMember.project_id == project.public_id
    ).first()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project member not found")
    db.delete(member)
    db.commit()

def list_project_members(db: Session, project_id: str) -> list[dict]:
    members = db.query(ProjectMember).filter(ProjectMember.project_id == project_id).all()
    user_ids = [m.user_id for m in members]
    users = db.query(User).filter(User.public_id.in_(user_ids)).all()
    user_map = {u.public_id: u for u in users}

    res = []
    for m in members:
        u = user_map.get(m.user_id)
        res.append({
            "user_public_id": m.user_id,
            "project_id": m.project_id,
            "role": m.role,
            "email": u.email if u else None,
            "full_name": u.full_name if u else None,
        })
    return res
