#!/usr/bin/env python3
"""Create the first authorized owner without demo credentials or email sending."""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import select
from receptionist.db import SessionLocal
from receptionist.models import Membership, Tenant, User, uid
from receptionist.security import hash_password


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--clinic-name", required=True)
    parser.add_argument("--slug", required=True)
    args = parser.parse_args()
    password = getpass.getpass("New owner password (minimum 14 characters): ")
    if len(password) < 14 or password != getpass.getpass("Repeat password: "):
        raise SystemExit("Password length or confirmation failed; no account created.")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == args.email.lower())):
            raise SystemExit("Account already exists; use existing authenticated account management.")
        if db.scalar(select(Tenant).where(Tenant.slug == args.slug)):
            raise SystemExit("Clinic slug already exists; membership must be explicitly granted.")
        tenant = Tenant(id=uid(), name=args.clinic_name, slug=args.slug, mode="paused", working_hours={})
        user = User(id=uid(), email=args.email.lower(), name="مدیر مرکز", password_hash=hash_password(password))
        db.add_all([tenant, user])
        db.flush()
        db.add(Membership(user_id=user.id, tenant_id=tenant.id, role="owner"))
        db.commit()
    print("Owner created. Complete clinic setup and publish approved hours before enabling reception.")


if __name__ == "__main__":
    main()

