"""
Creates (or resets the password of) a default admin account for the
admin dashboard. Re-runnable — upserts on username.

Run from the project root:
    python -m db.seed_admin
    python -m db.seed_admin --username ops --password "SomethingBetter123!"

Reads ADMIN_USERNAME / ADMIN_PASSWORD from the environment if present
(falls back to admin / ChangeMe123! for local dev — change this before
deploying anywhere real).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.admin_auth import hash_password
from app.config import settings
from app.database import engine

DEFAULT_USERNAME = settings.admin_username
DEFAULT_PASSWORD = settings.admin_password


def seed(username: str = DEFAULT_USERNAME, password: str = DEFAULT_PASSWORD):
    password_hash = hash_password(password)

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO admin_users (username, password_hash)
            VALUES (:username, :password_hash)
            ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash
        """), {"username": username, "password_hash": password_hash})

    print(f"Admin user '{username}' is ready.")
    if password == "ChangeMe123!":
        print("WARNING: using the default password — set ADMIN_PASSWORD before any real deployment.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    args = parser.parse_args()
    seed(args.username, args.password)
