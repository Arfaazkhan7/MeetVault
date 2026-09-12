from sqlalchemy.orm import Session
from app.models.user import User
from app.models.company import Company, CompanyMember
from app.core.security import hash_password, verify_password


def _generate_public_id(db: Session) -> str:
    count = db.query(User).count() + 1
    return f"USR-{count:04d}"


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email.lower().strip()).first()


def get_user_by_public_id(db: Session, public_id: str) -> User | None:
    return db.query(User).filter(User.public_id == public_id).first()


def create_user(
    db: Session,
    full_name: str,
    email: str,
    plain_password: str,
    organization_name: str | None = None,
    account_type: str | None = "personal",
) -> User:
    email = email.lower().strip()
    if get_user_by_email(db, email):
        raise ValueError("A user with this email already exists")
    user = User(
        public_id=_generate_public_id(db),
        email=email,
        full_name=full_name.strip(),
        hashed_password=hash_password(plain_password),
        account_type=account_type or "personal",
    )
    db.add(user)
    db.flush()

    # Auto-create a default workspace and project for the user
    from app.services.company_service import create_company
    from app.services.project_service import create_project

    if account_type == "organization" and organization_name and organization_name.strip():
        comp_name = f"{organization_name.strip()} Workspace"
    else:
        comp_name = f"{user.full_name}'s Personal Workspace"

    comp = create_company(db, comp_name, None, user)
    create_project(db, comp.public_id, "General", "Default project for meetings", user)

    db.commit()
    db.refresh(user)
    return user


def get_or_create_firebase_personal_user(
    db: Session,
    email: str,
    full_name: str | None,
) -> User:
    email = email.lower().strip()
    user = get_user_by_email(db, email)
    if user:
        return user

    display_name = (full_name or email.split("@")[0]).strip()
    user = User(
        public_id=_generate_public_id(db),
        email=email,
        full_name=display_name,
        hashed_password=None,
        account_type="personal",
    )
    db.add(user)
    db.flush()

    from app.services.company_service import create_company
    from app.services.project_service import create_project

    comp = create_company(db, f"{display_name}'s Personal Workspace", None, user)
    create_project(db, comp.public_id, "General", "Default project for meetings", user)
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


def authenticate_personal_user(db: Session, email: str, plain_password: str) -> User | None:
    """Authenticate personal mode user."""
    return authenticate_user(db, email, plain_password)


def authenticate_workspace_user(
    db: Session, workspace_code: str, email: str, plain_password: str
) -> tuple[User, Company] | None:
    """
    Authenticate workspace mode user:
    1. Check workspace existence by workspace_code or public_id
    2. Check user credentials
    3. Check active workspace membership
    """
    code = workspace_code.strip()
    company = (
        db.query(Company)
        .filter(
            (Company.workspace_code == code) | (Company.public_id == code),
            Company.deleted_at.is_(None),
        )
        .first()
    )
    if not company:
        return None

    user = authenticate_user(db, email, plain_password)
    if not user:
        return None

    membership = (
        db.query(CompanyMember)
        .filter(
            CompanyMember.user_id == user.public_id,
            CompanyMember.company_id == company.public_id,
        )
        .first()
    )
    if not membership:
        return None

    return user, company


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
