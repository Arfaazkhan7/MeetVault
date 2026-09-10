from enum import Enum

class Role(str, Enum):
    SUPER_ADMIN     = "SUPER_ADMIN"
    COMPANY_ADMIN   = "COMPANY_ADMIN"
    PROJECT_MANAGER = "PROJECT_MANAGER"
    MEMBER          = "MEMBER"
    PERSONAL_USER   = "PERSONAL_USER"

# Ordered hierarchy: higher index = more privileged
_ROLE_ORDER = [Role.PERSONAL_USER, Role.MEMBER, Role.PROJECT_MANAGER, Role.COMPANY_ADMIN, Role.SUPER_ADMIN]

def role_gte(role: Role, minimum: Role) -> bool:
    """Return True if `role` is at least as privileged as `minimum`."""
    try:
        return _ROLE_ORDER.index(role) >= _ROLE_ORDER.index(minimum)
    except ValueError:
        return False


class ProjectRole(str, Enum):
    ADMIN  = "ADMIN"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"

_PROJECT_ROLE_ORDER = [ProjectRole.VIEWER, ProjectRole.MEMBER, ProjectRole.ADMIN]

def project_role_gte(role: ProjectRole, minimum: ProjectRole) -> bool:
    try:
        return _PROJECT_ROLE_ORDER.index(role) >= _PROJECT_ROLE_ORDER.index(minimum)
    except ValueError:
        return False
