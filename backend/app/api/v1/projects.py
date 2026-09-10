from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional

from app.db.session import get_db
from app.core.dependencies import get_current_user, require_role, get_project_and_authorize, require_project_admin
from app.core.roles import Role, ProjectRole
from app.models.user import User
from app.models.project import Project
from app.schemas.project import (
    CreateProjectRequest,
    UpdateProjectRequest,
    ProjectResponse,
    AddProjectMemberRequest,
    UpdateProjectMemberRoleRequest,
    ProjectMemberResponse,
)
from app.services.project_service import (
    create_project,
    list_projects_for_company,
    list_all_projects_for_user,
    update_project,
    archive_project,
    add_project_member,
    remove_project_member,
    list_project_members
)
from app.models.company import CompanyMember

router = APIRouter(tags=["projects"])


# ── Global user-scoped listing ────────────────────────────────────────────
@router.get("/projects", response_model=list[ProjectResponse])
def list_all_projects(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_all_projects_for_user(db, current_user.public_id)


# ── Company-scoped listing/creation ──────────────────────────────────────
@router.get("/companies/{company_id}/projects", response_model=list[ProjectResponse])
def list_company_projects(
    company_id: str,
    status: Optional[str] = "ACTIVE",
    membership: CompanyMember = Depends(require_role(Role.MEMBER)),
    db: Session = Depends(get_db),
):
    return list_projects_for_company(db, company_id, status)


@router.post("/companies/{company_id}/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_new_project(
    company_id: str,
    payload: CreateProjectRequest,
    current_user: User = Depends(get_current_user),
    membership: CompanyMember = Depends(require_role(Role.PROJECT_MANAGER)),
    db: Session = Depends(get_db),
):
    return create_project(db, company_id, payload.name, payload.description, current_user)


# ── Project-scoped routes ────────────────────────────────────────────────
@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    project: Project = Depends(get_project_and_authorize),
):
    return project


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
def update_project_details(
    project_id: str,
    payload: UpdateProjectRequest,
    project: Project = Depends(require_project_admin),
    db: Session = Depends(get_db),
):
    return update_project(db, project, payload.name, payload.description)


@router.post("/projects/{project_id}/archive", response_model=ProjectResponse)
def archive_existing_project(
    project_id: str,
    project: Project = Depends(require_project_admin),
    db: Session = Depends(get_db),
):
    return archive_project(db, project)


# ── Project Members ──────────────────────────────────────────────────────
@router.get("/projects/{project_id}/members", response_model=list[ProjectMemberResponse])
def get_project_members(
    project_id: str,
    project: Project = Depends(get_project_and_authorize),
    db: Session = Depends(get_db),
):
    return list_project_members(db, project_id)


@router.post("/projects/{project_id}/members", response_model=ProjectMemberResponse, status_code=status.HTTP_201_CREATED)
def assign_project_member(
    project_id: str,
    payload: AddProjectMemberRequest,
    project: Project = Depends(require_project_admin),
    db: Session = Depends(get_db),
):
    # Validate that the user to be added is actually a member of the company!
    from app.core.dependencies import get_membership
    try:
        get_membership(db, payload.user_public_id, project.company_id)
    except HTTPException:
        raise HTTPException(status_code=400, detail="User must be a member of the company to join a project")

    member = add_project_member(db, project, payload.user_public_id, payload.role)
    return list_project_members(db, project_id)[-1]  # Return fully joined


@router.delete("/projects/{project_id}/members/{user_public_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member_from_project(
    project_id: str,
    user_public_id: str,
    project: Project = Depends(require_project_admin),
    db: Session = Depends(get_db),
):
    remove_project_member(db, project, user_public_id)

