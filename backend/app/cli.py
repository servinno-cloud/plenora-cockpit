import argparse
import getpass
import os

from sqlalchemy import func, select

from .auth import hash_password
from .database import SessionLocal
from .models import Operator, OperatorRole


def create_owner(email: str, password: str) -> None:
    normalized = email.strip().casefold()
    if not normalized or "@" not in normalized:
        raise SystemExit("A valid owner email is required")
    if len(password) < 14:
        raise SystemExit("Owner password must contain at least 14 characters")
    with SessionLocal.begin() as db:
        if db.scalar(select(func.count()).select_from(Operator)):
            raise SystemExit("An operator already exists; bootstrap refused")
        db.add(
            Operator(
                email=normalized,
                password_hash=hash_password(password),
                role=OperatorRole.OWNER,
                active=True,
            )
        )
    print("OWNER created")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cockpit owner bootstrap")
    parser.add_argument("command", choices=["create-owner"])
    parser.add_argument("--email", default=os.getenv("COCKPIT_BOOTSTRAP_EMAIL", ""))
    args = parser.parse_args()
    password = os.getenv("COCKPIT_BOOTSTRAP_PASSWORD") or getpass.getpass("Owner password: ")
    create_owner(args.email, password)


if __name__ == "__main__":
    main()
