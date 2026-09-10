from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import datetime


class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str


class CreateWorkspaceAdminRequest(BaseModel):
    organization_name: str
    admin_name: str
    admin_email: EmailStr
    admin_password: str

    @field_validator("organization_name", "admin_name")
    @classmethod
    def not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Field cannot be blank")
        return v


class WorkspaceAdminResponse(BaseModel):
    workspace_id: str
    workspace_code: str
    organization_name: str
    admin_public_id: str
    admin_email: str
    admin_name: str
    created_at: datetime
    model_config = {"from_attributes": True}


class SystemStatsResponse(BaseModel):
    total_users: int
    total_workspaces: int
    total_projects: int
    total_meetings: int
    total_recordings: int
