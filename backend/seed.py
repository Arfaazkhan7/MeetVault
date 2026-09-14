import logging
from app.db.session import SessionLocal
from app.models.user import User
from app.core.security import hash_password
from app.services.admin_service import create_workspace_by_admin

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def seed():
    db = SessionLocal()
    try:
        # 1. Create System Admin
        admin_email = "system.admin@meetvault.com"
        admin_password = "AdminPassword123!"
        
        sys_admin = db.query(User).filter(User.email == admin_email).first()
        if not sys_admin:
            count = db.query(User).count() + 1
            sys_admin = User(
                public_id=f"USR-{count:04d}",
                email=admin_email,
                full_name="System Administrator",
                hashed_password=hash_password(admin_password),
                account_type="personal"  # Admins don't need a workspace strictly, but email prefix gives them power
            )
            db.add(sys_admin)
            db.commit()
            print(f"Created System Admin: {admin_email} / {admin_password}")
        else:
            print(f"System Admin already exists: {admin_email}")

        # 2. Create One Workspace Account (Organization)
        org_name = "Acme Corp"
        ws_admin_email = "workspace.admin@acmecorp.com"
        ws_admin_password = "WorkspacePassword123!"
        
        ws_admin = db.query(User).filter(User.email == ws_admin_email).first()
        if not ws_admin:
            workspace_data = create_workspace_by_admin(
                db=db,
                organization_name=org_name,
                admin_name="Acme Admin",
                admin_email=ws_admin_email,
                admin_password=ws_admin_password
            )
            print(f"Created Workspace Account:")
            print(f"  Organization: {workspace_data['organization_name']}")
            print(f"  Workspace Code: {workspace_data['workspace_code']}")
            print(f"  Workspace Admin Login: {ws_admin_email} / {ws_admin_password}")
        else:
            print(f"Workspace Admin already exists: {ws_admin_email}")

    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed()
