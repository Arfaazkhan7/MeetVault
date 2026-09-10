"""Phase 3 file generator — writes all remaining backend files for Company & User Management."""
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
""").lstrip()

# ─────────────────────────────────────────────────────────────────────────────
# DEPENDENCIES (extended)
# ─────────────────────────────────────────────────────────────────────────────
files["app/core/dependencies.py"] = textwrap.dedent("""
    from fastapi import Depends, HTTPException, status
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    from jose import JWTError
    from sqlalchemy.orm import Session

    from app.core.tokens import decode_token
    from app.core.roles import Role, role_gte
    from app.db.session import get_db
    from app.services.user_service import get_user_by_public_id
    from app.models.user import User
    from app.models.company import CompanyMember

    _bearer = HTTPBearer(auto_error=True)


    # ── Base auth dependency ──────────────────────────────────────────────────
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


    # ── Company membership helper ─────────────────────────────────────────────
    def get_membership(db: Session, user_public_id: str, company_public_id: str) -> CompanyMember:
        \"\"\"
        Return the CompanyMember record.
        Raises 403 if the user is not a member of that company.
        NOTE: company_public_id is looked up from DB — never trusted from client alone.
        \"\"\"
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


    # ── Role-checking dependency factory ─────────────────────────────────────
    def require_role(minimum_role: Role):
        \"\"\"
        Returns a FastAPI dependency that:
        1. Authenticates the user.
        2. Looks up their membership in the company identified by path param `company_id`.
        3. Checks their role is at least `minimum_role`.

        Usage:
            @router.post(...)
            def endpoint(
                company_id: str,
                member=Depends(require_role(Role.COMPANY_ADMIN)),
                db: Session = Depends(get_db),
            ):
                ...
        \"\"\"
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
""").lstrip()

# ─────────────────────────────────────────────────────────────────────────────
# SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────
files["app/schemas/company.py"] = textwrap.dedent("""
    from pydantic import BaseModel, field_validator
    from typing import Optional
    from app.core.roles import Role


    # ── Company ───────────────────────────────────────────────────────────────
    class CreateCompanyRequest(BaseModel):
        name: str
        domain: Optional[str] = None

        @field_validator("name")
        @classmethod
        def name_not_empty(cls, v: str) -> str:
            v = v.strip()
            if not v:
                raise ValueError("Company name cannot be blank")
            return v


    class CompanyResponse(BaseModel):
        public_id: str
        name: str
        domain: Optional[str]
        model_config = {"from_attributes": True}


    # ── Members ───────────────────────────────────────────────────────────────
    class AddMemberRequest(BaseModel):
        email: str              # look up user by email
        role: Role = Role.MEMBER
        department: Optional[str] = None
        job_title: Optional[str] = None


    class UpdateMemberRoleRequest(BaseModel):
        role: Role
        department: Optional[str] = None
        job_title: Optional[str] = None


    class MemberResponse(BaseModel):
        user_public_id: str
        email: str
        full_name: Optional[str]
        role: str
        department: Optional[str]
        job_title: Optional[str]
        model_config = {"from_attributes": True}


    # ── User profile ──────────────────────────────────────────────────────────
    class UpdateProfileRequest(BaseModel):
        full_name: Optional[str] = None
        phone: Optional[str] = None
        avatar_url: Optional[str] = None


    class UserProfileResponse(BaseModel):
        public_id: str
        email: str
        full_name: Optional[str]
        phone: Optional[str]
        avatar_url: Optional[str]
        model_config = {"from_attributes": True}
""").lstrip()

# ─────────────────────────────────────────────────────────────────────────────
# SERVICES
# ─────────────────────────────────────────────────────────────────────────────
files["app/services/company_service.py"] = textwrap.dedent("""
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
        \"\"\"Create a company and make the creator its COMPANY_ADMIN.\"\"\"
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
        \"\"\"Return member list with user details joined in Python (SQLite-safe).\"\"\"
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
""").lstrip()

files["app/services/user_service.py"] = textwrap.dedent("""
    from sqlalchemy.orm import Session
    from app.models.user import User
    from app.core.security import hash_password, verify_password


    def _generate_public_id(db: Session) -> str:
        count = db.query(User).count() + 1
        return f"USR-{count:04d}"


    def get_user_by_email(db: Session, email: str) -> User | None:
        return db.query(User).filter(User.email == email.lower().strip()).first()


    def get_user_by_public_id(db: Session, public_id: str) -> User | None:
        return db.query(User).filter(User.public_id == public_id).first()


    def create_user(db: Session, full_name: str, email: str, plain_password: str) -> User:
        email = email.lower().strip()
        if get_user_by_email(db, email):
            raise ValueError("A user with this email already exists")
        user = User(
            public_id=_generate_public_id(db),
            email=email,
            full_name=full_name.strip(),
            hashed_password=hash_password(plain_password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


    def authenticate_user(db: Session, email: str, plain_password: str) -> User | None:
        user = get_user_by_email(db, email)
        if not user or not user.hashed_password:
            return None
        if not verify_password(plain_password, user.hashed_password):
            return None
        return user


    def update_user_profile(
        db: Session,
        user: User,
        full_name: str | None,
        phone: str | None,
        avatar_url: str | None,
    ) -> User:
        if full_name is not None:
            user.full_name = full_name.strip()
        if phone is not None:
            user.phone = phone.strip()
        if avatar_url is not None:
            user.avatar_url = avatar_url.strip()
        db.commit()
        db.refresh(user)
        return user
""").lstrip()

# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────
files["app/api/v1/companies.py"] = textwrap.dedent("""
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
        \"\"\"Any authenticated user can create a company. They become its COMPANY_ADMIN.\"\"\"
        return create_company(db, payload.name, payload.domain, current_user)


    @router.get("", response_model=list[CompanyResponse])
    def my_companies(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        \"\"\"List all companies the current user is a member of.\"\"\"
        return list_user_companies(db, current_user.public_id)


    @router.get("/{company_id}", response_model=CompanyResponse)
    def get_company(
        company_id: str,
        membership=Depends(require_role(Role.MEMBER)),
        db: Session = Depends(get_db),
    ):
        \"\"\"Get company details. Any member may view.\"\"\"
        return get_company_or_404(db, company_id)


    # ── Member endpoints ──────────────────────────────────────────────────────

    @router.get("/{company_id}/members", response_model=list[MemberResponse])
    def list_members(
        company_id: str,
        membership=Depends(require_role(Role.MEMBER)),
        db: Session = Depends(get_db),
    ):
        \"\"\"List all members of the company. Any member may view.\"\"\"
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
        \"\"\"Add a user to the company by email. Requires COMPANY_ADMIN or higher.\"\"\"
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
        \"\"\"Update a member's role. Requires COMPANY_ADMIN or higher.\"\"\"
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
        \"\"\"Remove a member. Requires COMPANY_ADMIN. Cannot remove self.\"\"\"
        remove_member(db, company_id, user_public_id, current_user.public_id)
""").lstrip()

files["app/api/v1/users.py"] = textwrap.dedent("""
    from fastapi import APIRouter, Depends
    from sqlalchemy.orm import Session

    from app.db.session import get_db
    from app.core.dependencies import get_current_user
    from app.models.user import User
    from app.schemas.company import UpdateProfileRequest, UserProfileResponse
    from app.services.user_service import update_user_profile

    router = APIRouter(prefix="/users", tags=["users"])


    @router.get("/me", response_model=UserProfileResponse)
    def get_my_profile(current_user: User = Depends(get_current_user)):
        \"\"\"Return the current user's profile.\"\"\"
        return current_user


    @router.patch("/me", response_model=UserProfileResponse)
    def update_my_profile(
        payload: UpdateProfileRequest,
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        \"\"\"Update the current user's profile fields.\"\"\"
        return update_user_profile(
            db,
            current_user,
            payload.full_name,
            payload.phone,
            payload.avatar_url,
        )
""").lstrip()

# ─────────────────────────────────────────────────────────────────────────────
# MAIN — register new routers
# ─────────────────────────────────────────────────────────────────────────────
files["app/main.py"] = textwrap.dedent("""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from app.core.config import settings
    from app.api.v1 import health, auth, companies, users

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
""").lstrip()

# ─────────────────────────────────────────────────────────────────────────────
# TESTS
# ─────────────────────────────────────────────────────────────────────────────
files["tests/test_companies.py"] = textwrap.dedent("""
    \"\"\"
    Phase 3 — Company & User Management Tests
    Tests: authorized access, unauthorized access, cross-company isolation, role enforcement.
    \"\"\"
    import pytest
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.main import app
    from app.db.session import get_db
    from app.models.base import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()


    app.dependency_overrides[get_db] = override_get_db


    @pytest.fixture(autouse=True)
    def setup_db():
        Base.metadata.create_all(bind=engine)
        yield
        Base.metadata.drop_all(bind=engine)


    @pytest.fixture()
    def client(setup_db):
        return TestClient(app)


    # ── Helper functions ──────────────────────────────────────────────────────

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


    def create_company(client, token, name="Acme Corp", domain=None):
        r = client.post("/api/v1/companies", json={"name": name, "domain": domain},
                        headers=auth_headers(token))
        assert r.status_code == 201, r.text
        return r.json()


    # ─────────────────────────────────────────────────────────────────────────
    # Company creation
    # ─────────────────────────────────────────────────────────────────────────

    class TestCompanyCreation:
        def test_create_company_success(self, client):
            register(client, "alice@example.com")
            token = login(client, "alice@example.com")
            company = create_company(client, token)
            assert company["public_id"].startswith("COMP-")
            assert company["name"] == "Acme Corp"

        def test_create_company_requires_auth(self, client):
            r = client.post("/api/v1/companies", json={"name": "Ghost Corp"})
            assert r.status_code == 401

        def test_create_company_blank_name(self, client):
            register(client, "bob@example.com")
            token = login(client, "bob@example.com")
            r = client.post("/api/v1/companies", json={"name": "   "},
                            headers=auth_headers(token))
            assert r.status_code == 422

        def test_creator_becomes_company_admin(self, client):
            register(client, "alice@example.com")
            token = login(client, "alice@example.com")
            company = create_company(client, token)
            members = client.get(
                f"/api/v1/companies/{company['public_id']}/members",
                headers=auth_headers(token),
            ).json()
            assert len(members) == 1
            assert members[0]["role"] == "COMPANY_ADMIN"

        def test_list_my_companies(self, client):
            register(client, "alice@example.com")
            token = login(client, "alice@example.com")
            create_company(client, token, "Company A")
            create_company(client, token, "Company B")
            r = client.get("/api/v1/companies", headers=auth_headers(token))
            assert r.status_code == 200
            assert len(r.json()) == 2


    # ─────────────────────────────────────────────────────────────────────────
    # Member management
    # ─────────────────────────────────────────────────────────────────────────

    class TestMemberManagement:
        def _setup(self, client):
            register(client, "admin@example.com", "Admin User")
            register(client, "member@example.com", "Member User")
            admin_token = login(client, "admin@example.com")
            company = create_company(client, admin_token)
            return admin_token, company["public_id"]

        def test_add_member_success(self, client):
            admin_token, cid = self._setup(client)
            r = client.post(
                f"/api/v1/companies/{cid}/members",
                json={"email": "member@example.com", "role": "MEMBER"},
                headers=auth_headers(admin_token),
            )
            assert r.status_code == 201, r.text
            assert r.json()["role"] == "MEMBER"

        def test_add_member_nonexistent_user(self, client):
            admin_token, cid = self._setup(client)
            r = client.post(
                f"/api/v1/companies/{cid}/members",
                json={"email": "nobody@example.com", "role": "MEMBER"},
                headers=auth_headers(admin_token),
            )
            assert r.status_code == 404

        def test_add_member_duplicate_rejected(self, client):
            admin_token, cid = self._setup(client)
            payload = {"email": "member@example.com", "role": "MEMBER"}
            client.post(f"/api/v1/companies/{cid}/members", json=payload,
                        headers=auth_headers(admin_token))
            r = client.post(f"/api/v1/companies/{cid}/members", json=payload,
                            headers=auth_headers(admin_token))
            assert r.status_code == 409

        def test_update_member_role(self, client):
            admin_token, cid = self._setup(client)
            client.post(f"/api/v1/companies/{cid}/members",
                        json={"email": "member@example.com", "role": "MEMBER"},
                        headers=auth_headers(admin_token))
            # get member's public_id from member list
            members = client.get(f"/api/v1/companies/{cid}/members",
                                 headers=auth_headers(admin_token)).json()
            member_uid = next(m["user_public_id"] for m in members if "member@" in m["email"])
            r = client.patch(
                f"/api/v1/companies/{cid}/members/{member_uid}",
                json={"role": "PROJECT_MANAGER"},
                headers=auth_headers(admin_token),
            )
            assert r.status_code == 200
            assert r.json()["role"] == "PROJECT_MANAGER"

        def test_remove_member(self, client):
            admin_token, cid = self._setup(client)
            client.post(f"/api/v1/companies/{cid}/members",
                        json={"email": "member@example.com", "role": "MEMBER"},
                        headers=auth_headers(admin_token))
            members = client.get(f"/api/v1/companies/{cid}/members",
                                 headers=auth_headers(admin_token)).json()
            member_uid = next(m["user_public_id"] for m in members if "member@" in m["email"])
            r = client.delete(f"/api/v1/companies/{cid}/members/{member_uid}",
                              headers=auth_headers(admin_token))
            assert r.status_code == 204
            members_after = client.get(f"/api/v1/companies/{cid}/members",
                                       headers=auth_headers(admin_token)).json()
            assert all(m["email"] != "member@example.com" for m in members_after)

        def test_cannot_remove_self(self, client):
            admin_token, cid = self._setup(client)
            members = client.get(f"/api/v1/companies/{cid}/members",
                                 headers=auth_headers(admin_token)).json()
            admin_uid = members[0]["user_public_id"]
            r = client.delete(f"/api/v1/companies/{cid}/members/{admin_uid}",
                              headers=auth_headers(admin_token))
            assert r.status_code == 400


    # ─────────────────────────────────────────────────────────────────────────
    # Authorization & Role enforcement
    # ─────────────────────────────────────────────────────────────────────────

    class TestAuthorization:
        def _setup(self, client):
            register(client, "admin@example.com", "Admin")
            register(client, "member@example.com", "Member")
            admin_token = login(client, "admin@example.com")
            member_token = login(client, "member@example.com")
            company = create_company(client, admin_token)
            cid = company["public_id"]
            client.post(f"/api/v1/companies/{cid}/members",
                        json={"email": "member@example.com", "role": "MEMBER"},
                        headers=auth_headers(admin_token))
            return admin_token, member_token, cid

        def test_member_can_view_members(self, client):
            _, member_token, cid = self._setup(client)
            r = client.get(f"/api/v1/companies/{cid}/members",
                           headers=auth_headers(member_token))
            assert r.status_code == 200

        def test_member_cannot_add_members(self, client):
            _, member_token, cid = self._setup(client)
            register(client, "newuser@example.com")
            r = client.post(f"/api/v1/companies/{cid}/members",
                            json={"email": "newuser@example.com", "role": "MEMBER"},
                            headers=auth_headers(member_token))
            assert r.status_code == 403

        def test_member_cannot_remove_members(self, client):
            admin_token, member_token, cid = self._setup(client)
            members = client.get(f"/api/v1/companies/{cid}/members",
                                 headers=auth_headers(admin_token)).json()
            admin_uid = next(m["user_public_id"] for m in members if "admin@" in m["email"])
            r = client.delete(f"/api/v1/companies/{cid}/members/{admin_uid}",
                              headers=auth_headers(member_token))
            assert r.status_code == 403

        def test_unauthenticated_cannot_view_members(self, client):
            register(client, "admin@example.com")
            token = login(client, "admin@example.com")
            company = create_company(client, token)
            r = client.get(f"/api/v1/companies/{company['public_id']}/members")
            assert r.status_code == 401


    # ─────────────────────────────────────────────────────────────────────────
    # Cross-company isolation
    # ─────────────────────────────────────────────────────────────────────────

    class TestCrossCompanyIsolation:
        def test_user_from_company_a_cannot_see_company_b_members(self, client):
            # User A creates Company A
            register(client, "usera@example.com", "User A")
            token_a = login(client, "usera@example.com")
            company_a = create_company(client, token_a, "Company A")

            # User B creates Company B
            register(client, "userb@example.com", "User B")
            token_b = login(client, "userb@example.com")
            company_b = create_company(client, token_b, "Company B")

            # User A tries to access Company B's members — must get 403
            r = client.get(
                f"/api/v1/companies/{company_b['public_id']}/members",
                headers=auth_headers(token_a),
            )
            assert r.status_code == 403

        def test_user_from_company_a_cannot_add_to_company_b(self, client):
            register(client, "usera@example.com")
            token_a = login(client, "usera@example.com")
            register(client, "userb@example.com")
            token_b = login(client, "userb@example.com")
            company_b = create_company(client, token_b, "Company B")

            r = client.post(
                f"/api/v1/companies/{company_b['public_id']}/members",
                json={"email": "usera@example.com", "role": "MEMBER"},
                headers=auth_headers(token_a),
            )
            assert r.status_code == 403

        def test_each_user_only_sees_own_companies(self, client):
            register(client, "usera@example.com")
            token_a = login(client, "usera@example.com")
            create_company(client, token_a, "Company A")

            register(client, "userb@example.com")
            token_b = login(client, "userb@example.com")
            create_company(client, token_b, "Company B")

            companies_a = client.get("/api/v1/companies", headers=auth_headers(token_a)).json()
            companies_b = client.get("/api/v1/companies", headers=auth_headers(token_b)).json()

            assert all(c["name"] == "Company A" for c in companies_a)
            assert all(c["name"] == "Company B" for c in companies_b)


    # ─────────────────────────────────────────────────────────────────────────
    # User profile
    # ─────────────────────────────────────────────────────────────────────────

    class TestUserProfile:
        def test_get_profile(self, client):
            register(client, "alice@example.com", "Alice")
            token = login(client, "alice@example.com")
            r = client.get("/api/v1/users/me", headers=auth_headers(token))
            assert r.status_code == 200
            assert r.json()["email"] == "alice@example.com"
            assert "hashed_password" not in r.text

        def test_update_profile(self, client):
            register(client, "alice@example.com", "Alice")
            token = login(client, "alice@example.com")
            r = client.patch(
                "/api/v1/users/me",
                json={"full_name": "Alice Updated", "phone": "+91-9999999999"},
                headers=auth_headers(token),
            )
            assert r.status_code == 200
            body = r.json()
            assert body["full_name"] == "Alice Updated"
            assert body["phone"] == "+91-9999999999"

        def test_profile_requires_auth(self, client):
            r = client.get("/api/v1/users/me")
            assert r.status_code == 401
""").lstrip()

# ─────────────────────────────────────────────────────────────────────────────
# Write all files
# ─────────────────────────────────────────────────────────────────────────────
for rel, content in files.items():
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  wrote  {path}")

print("done")
