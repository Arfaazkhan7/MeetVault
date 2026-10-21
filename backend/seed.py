import os
import logging
from app.db.session import SessionLocal
from app.models.user import User
from app.core.security import hash_password
from app.services.user_service import provision_admin_user
from app.services.admin_service import create_workspace_by_admin

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def seed():
    db = SessionLocal()
    try:
        # 1. Provision System Admin via conscious configuration / env variables
        admin_email = os.getenv("INITIAL_ADMIN_EMAIL", "system.admin@meetvault.com")
        admin_password = os.getenv("INITIAL_ADMIN_PASSWORD", "SysAdminPass123!")

        sys_admin = provision_admin_user(
            db=db,
            email=admin_email,
            plain_password=admin_password,
            full_name="System Administrator",
        )
        print(f"Provisioned System Admin (account_type='{sys_admin.account_type}'): {admin_email}")

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
