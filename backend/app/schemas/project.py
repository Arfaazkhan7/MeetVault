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
