"""
Administrative CLI management tool for MeetVault.
Provides conscious, explicit provisioning and management of System Administrators.
Administrators cannot be created through public API registration.
"""

import argparse
import sys
from app.db.session import SessionLocal
from app.models.user import User
from app.services.user_service import provision_admin_user, get_user_by_email


def cmd_provision(args, db=None):
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        user = provision_admin_user(
            db=db,
            email=args.email,
            plain_password=args.password,
            full_name=args.name,
        )
        print(f"Successfully provisioned System Admin: {user.email} (ID: {user.public_id}, account_type: {user.account_type})")
        return user
    finally:
        if close_db:
            db.close()


def cmd_demote(args, db=None):
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        user = get_user_by_email(db, args.email)
        if not user:
            print(f"Error: User '{args.email}' not found.", file=sys.stderr)
            sys.exit(1)
        user.account_type = "personal"
        db.commit()
        print(f"Successfully demoted '{user.email}' to personal account.")
        return user
    finally:
        if close_db:
            db.close()


def cmd_list(args, db=None):
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        admins = db.query(User).filter(User.account_type == "admin").all()
        if not admins:
            print("No system administrators found.")
            return admins
        print(f"Found {len(admins)} system administrator(s):")
        for a in admins:
            print(f" - {a.public_id}: {a.email} ({a.full_name})")
        return admins
    finally:
        if close_db:
            db.close()


def main():
    parser = argparse.ArgumentParser(description="MeetVault Admin Management CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Provision command
    p_provision = subparsers.add_parser("provision", help="Provision or promote a System Admin")
    p_provision.add_argument("--email", required=True, help="Admin email address")
    p_provision.add_argument("--password", required=True, help="Admin password")
    p_provision.add_argument("--name", default="System Administrator", help="Admin full name")
    p_provision.set_defaults(func=cmd_provision)

    # Demote command
    p_demote = subparsers.add_parser("demote", help="Demote a System Admin to personal account")
    p_demote.add_argument("--email", required=True, help="User email address")
    p_demote.set_defaults(func=cmd_demote)

    # List command
    p_list = subparsers.add_parser("list", help="List all System Admins")
    p_list.set_defaults(func=cmd_list)

    parsed = parser.parse_args()
    parsed.func(parsed)


if __name__ == "__main__":
    main()
