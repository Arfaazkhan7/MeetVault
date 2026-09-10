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
