from pydantic import BaseModel, EmailStr, field_validator
import re


# ── Password strength validator ────────────────────────────────────────────────
def _validate_password_strength(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", v):
        raise ValueError("Password must contain at least one digit")
    return v


# ── Registration ───────────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    account_type: str | None = "personal"
    organization_name: str | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)

    @field_validator("full_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Full name cannot be blank")
        return v


# ── Login Requests ─────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class PersonalLoginRequest(BaseModel):
    email: EmailStr
    password: str


class WorkspaceLoginRequest(BaseModel):
    workspace_code: str
    email: EmailStr
    password: str

    @field_validator("workspace_code")
    @classmethod
    def code_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Workspace code cannot be blank")
        return v


class FirebaseLoginRequest(BaseModel):
    id_token: str

    @field_validator("id_token")
    @classmethod
    def token_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Firebase ID token cannot be blank")
        return v


# ── Token payloads ─────────────────────────────────────────────────────────────
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    workspace_id: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


# ── User responses — NEVER include hashed_password ────────────────────────────
class UserResponse(BaseModel):
    public_id: str
    email: str
    full_name: str | None

    model_config = {"from_attributes": True}


class MeResponse(BaseModel):
    public_id: str
    email: str
    full_name: str | None
    current_workspace_id: str | None = None
    account_type: str = "personal"

    model_config = {"from_attributes": True}
