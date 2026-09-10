"""Phase 4 file generator — writes all remaining backend files for Project Management."""
import pathlib, textwrap

ROOT = pathlib.Path("backend")

files = {}

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS / ENUMS
# ─────────────────────────────────────────────────────────────────────────────
files["app/core/roles.py"] = textwrap.dedent("""
    from enum import Enum

    class Role(str, Enum):
        SUPER_ADMIN     = "SUPER_ADMIN"
        COMPANY_ADMIN   = "COMPANY_ADMIN"
        PROJECT_MANAGER = "PROJECT_MANAGER"
        MEMBER          = "MEMBER"

    # Ordered hierarchy: higher index = more privileged
    _ROLE_ORDER = [Role.MEMBER, Role.PROJECT_MANAGER, Role.COMPANY_ADMIN, Role.SUPER_ADMIN]

    def role_gte(role: Role, minimum: Role) -> bool:
        \"\"\"Return True if `role` is at least as privileged as `minimum`.\"\"\"
        return _ROLE_ORDER.index(role) >= _ROLE_ORDER.index(minimum)


    class ProjectRole(str, Enum):
        ADMIN  = "ADMIN"
        MEMBER = "MEMBER"
        VIEWER = "VIEWER"

    _PROJECT_ROLE_ORDER = [ProjectRole.VIEWER, ProjectRole.MEMBER, ProjectRole.ADMIN]

    def project_role_gte(role: ProjectRole, minimum: ProjectRole) -> bool:
        return _PROJECT_ROLE_ORDER.index(role) >= _PROJECT_ROLE_ORDER.index(minimum)
""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────────────────────────────────────
files["app/models/project.py"] = textwrap.dedent("""
    from sqlalchemy import Column, String, DateTime, UniqueConstraint
    from sqlalchemy.orm import relationship

    from app.models.base import Base


    class Project(Base):
        __tablename__ = "projects"

        public_id = Column(String, unique=True, index=True, nullable=False)
        company_id = Column(String, nullable=False, index=True)
        name = Column(String, nullable=False)
        description = Column(String, nullable=True)
        status = Column(String, nullable=False, default="ACTIVE") # ACTIVE, ARCHIVED
        deleted_at = Column(DateTime(timezone=True), nullable=True)

        company = relationship(
            "Company",
            primaryjoin="foreign(Project.company_id) == Company.public_id",
            back_populates="projects",
        )
        members = relationship(
            "ProjectMember",
            primaryjoin="Project.public_id == foreign(ProjectMember.project_id)",
            back_populates="project",
            lazy="dynamic",
            cascade="all, delete-orphan",
        )
        meetings = relationship("Meeting", back_populates="project")


    class ProjectMember(Base):
        __tablename__ = "project_members"

        __table_args__ = (
            UniqueConstraint("user_id", "project_id", name="uq_member_project"),
        )

        user_id = Column(String, nullable=False, index=True)
        project_id = Column(String, nullable=False, index=True)
        role = Column(String, nullable=False, default="MEMBER")

        project = relationship(
            "Project",
            primaryjoin="foreign(ProjectMember.project_id) == Project.public_id",
            back_populates="members",
        )
        user = relationship(
            "User",
            primaryjoin="foreign(ProjectMember.user_id) == User.public_id",
        )
""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────
files["app/schemas/project.py"] = textwrap.dedent("""
    from pydantic import BaseModel, field_validator
    from typing import Optional
    from app.core.roles import ProjectRole


    class CreateProjectRequest(BaseModel):
        name: str
        description: Optional[str] = None

        @field_validator("name")
        @classmethod
        def name_not_empty(cls, v: str) -> str:
            v = v.strip()
            if not v:
                raise ValueError("Project name cannot be blank")
            return v


    class UpdateProjectRequest(BaseModel):
        name: Optional[str] = None
        description: Optional[str] = None


    class ProjectResponse(BaseModel):
        public_id: str
        company_id: str
        name: str
        description: Optional[str]
        status: str
        model_config = {"from_attributes": True}


    class AddProjectMemberRequest(BaseModel):
        user_public_id: str
        role: ProjectRole = ProjectRole.MEMBER


    class UpdateProjectMemberRoleRequest(BaseModel):
        role: ProjectRole


    class ProjectMemberResponse(BaseModel):
        user_public_id: str
        project_id: str
        role: str
        email: Optional[str] = None
        full_name: Optional[str] = None
        model_config = {"from_attributes": True}
""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# DEPENDENCIES
# ─────────────────────────────────────────────────────────────────────────────
files["app/core/dependencies.py"] = textwrap.dedent("""
    from fastapi import Depends, HTTPException, status
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    from jose import JWTError
    from sqlalchemy.orm import Session

    from app.core.tokens import decode_token
    from app.core.roles import Role, role_gte, ProjectRole, project_role_gte
    from app.db.session import get_db
    from app.services.user_service import get_user_by_public_id
    from app.models.user import User
    from app.models.company import CompanyMember
    from app.models.project import Project, ProjectMember

    _bearer = HTTPBearer(auto_error=True)

    def get_current_user(
        credentials: HTTPAuthorizationCredentials = Depends(_bearer),
        db: Session = Depends(get_db),
    ) -> User:
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
        \"\"\"
        Fetch project by ID, ensure user is a member of its company.
        Also returns the project.
        \"\"\"
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
        \"\"\"
        Ensure user has Company Admin/Project Manager role OR is a Project Admin.
        \"\"\"
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
""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# SERVICES
# ─────────────────────────────────────────────────────────────────────────────
files["app/services/project_service.py"] = textwrap.dedent("""
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
""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────
files["app/api/v1/projects.py"] = textwrap.dedent("""
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
        update_project,
        archive_project,
        add_project_member,
        remove_project_member,
        list_project_members
    )
    from app.models.company import CompanyMember

    router = APIRouter(tags=["projects"])


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

""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN — register new routers
# ─────────────────────────────────────────────────────────────────────────────
files["app/main.py"] = textwrap.dedent("""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from app.core.config import settings
    from app.api.v1 import health, auth, companies, users, projects

    app = FastAPI(
        title=settings.PROJECT_NAME,
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url=f"{settings.API_V1_PREFIX}/docs",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.ENVIRONMENT == "development" else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router,     prefix=settings.API_V1_PREFIX)
    app.include_router(auth.router,       prefix=settings.API_V1_PREFIX)
    app.include_router(companies.router,  prefix=settings.API_V1_PREFIX)
    app.include_router(users.router,      prefix=settings.API_V1_PREFIX)
    app.include_router(projects.router,   prefix=settings.API_V1_PREFIX)
""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# TESTS
# ─────────────────────────────────────────────────────────────────────────────
files["tests/test_projects.py"] = textwrap.dedent("""
    \"\"\"Phase 4 - Project Management Tests - test DB provided by conftest.py\"\"\"

    def register(client, email, name="Test User", password="StrongPass1"):
        r = client.post("/api/v1/auth/register", json={
            "full_name": name, "email": email, "password": password,
        })
        assert r.status_code == 201, r.text
        return r.json()

    def login(client, email, password="StrongPass1"):
        r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    def auth_headers(token):
        return {"Authorization": f"Bearer {token}"}

    def setup_scenario(client):
        # A: Company Admin
        admin = register(client, "admin@example.com")
        token = login(client, "admin@example.com")
        comp = client.post("/api/v1/companies", json={"name": "Acme Corp"}, headers=auth_headers(token)).json()
        cid = comp["public_id"]
        
        # B: Normal member
        mem1 = register(client, "mem1@example.com")
        client.post(f"/api/v1/companies/{cid}/members", json={"email": "mem1@example.com", "role": "MEMBER"}, headers=auth_headers(token))
        
        return token, cid, admin, mem1

    def test_create_project_as_admin(client):
        token, cid, admin, _ = setup_scenario(client)
        r = client.post(f"/api/v1/companies/{cid}/projects", json={"name": "Alpha"}, headers=auth_headers(token))
        assert r.status_code == 201
        p = r.json()
        assert p["name"] == "Alpha"
        assert p["status"] == "ACTIVE"
        assert p["company_id"] == cid
        assert p["public_id"].startswith("PRJ-")

    def test_create_project_insufficient_role(client):
        _, cid, _, mem1 = setup_scenario(client)
        token = login(client, "mem1@example.com")
        r = client.post(f"/api/v1/companies/{cid}/projects", json={"name": "Beta"}, headers=auth_headers(token))
        assert r.status_code == 403

    def test_get_project_and_list(client):
        token, cid, _, _ = setup_scenario(client)
        p = client.post(f"/api/v1/companies/{cid}/projects", json={"name": "Alpha"}, headers=auth_headers(token)).json()
        pid = p["public_id"]
        
        r = client.get(f"/api/v1/projects/{pid}", headers=auth_headers(token))
        assert r.status_code == 200
        assert r.json()["name"] == "Alpha"
        
        lst = client.get(f"/api/v1/companies/{cid}/projects", headers=auth_headers(token)).json()
        assert len(lst) == 1

    def test_cross_company_isolation(client):
        tokenA, cidA, _, _ = setup_scenario(client)
        p = client.post(f"/api/v1/companies/{cidA}/projects", json={"name": "Alpha"}, headers=auth_headers(tokenA)).json()
        pid = p["public_id"]
        
        # User B makes Company B
        register(client, "userb@example.com")
        tokenB = login(client, "userb@example.com")
        compB = client.post("/api/v1/companies", json={"name": "Beta Corp"}, headers=auth_headers(tokenB)).json()
        
        # User B tries to access Project Alpha
        r = client.get(f"/api/v1/projects/{pid}", headers=auth_headers(tokenB))
        assert r.status_code == 403

    def test_update_and_archive(client):
        token, cid, _, _ = setup_scenario(client)
        p = client.post(f"/api/v1/companies/{cid}/projects", json={"name": "Alpha"}, headers=auth_headers(token)).json()
        pid = p["public_id"]
        
        r = client.patch(f"/api/v1/projects/{pid}", json={"name": "Alpha V2"}, headers=auth_headers(token))
        assert r.status_code == 200
        assert r.json()["name"] == "Alpha V2"
        
        r = client.post(f"/api/v1/projects/{pid}/archive", headers=auth_headers(token))
        assert r.status_code == 200
        assert r.json()["status"] == "ARCHIVED"
        
        # Check listing active doesn't return it (unless specified)
        lst = client.get(f"/api/v1/companies/{cid}/projects?status=ACTIVE", headers=auth_headers(token)).json()
        assert len(lst) == 0

    def test_project_members(client):
        token, cid, _, mem1 = setup_scenario(client)
        p = client.post(f"/api/v1/companies/{cid}/projects", json={"name": "Alpha"}, headers=auth_headers(token)).json()
        pid = p["public_id"]
        
        r = client.post(f"/api/v1/projects/{pid}/members", json={"user_public_id": mem1["public_id"], "role": "MEMBER"}, headers=auth_headers(token))
        assert r.status_code == 201
        
        mems = client.get(f"/api/v1/projects/{pid}/members", headers=auth_headers(token)).json()
        # Admin is auto-added, plus mem1
        assert len(mems) == 2
        
        client.delete(f"/api/v1/projects/{pid}/members/{mem1['public_id']}", headers=auth_headers(token))
        mems = client.get(f"/api/v1/projects/{pid}/members", headers=auth_headers(token)).json()
        assert len(mems) == 1

""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# FLUTTER UI (Mock Foundation)
# ─────────────────────────────────────────────────────────────────────────────
files["frontend/lib/features/projects/projects_screen.dart"] = textwrap.dedent("""
    // Placeholder for Phase 4 Flutter UI constraint
    import 'package:flutter/material.dart';

    class ProjectsScreen extends StatelessWidget {
      const ProjectsScreen({super.key});

      @override
      Widget build(BuildContext context) {
        return Scaffold(
          appBar: AppBar(title: const Text('Projects Dashboard')),
          body: const Center(
            child: Text('Project listing and dashboard will be implemented here.'),
          ),
          floatingActionButton: FloatingActionButton(
            onPressed: () {},
            child: const Icon(Icons.add),
          ),
        );
      }
    }
""").lstrip()


# ─────────────────────────────────────────────────────────────────────────────
# Write all files
# ─────────────────────────────────────────────────────────────────────────────
for rel, content in files.items():
    path = ROOT.parent / rel if rel.startswith("frontend/") else ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  wrote  {path}")

print("done")
