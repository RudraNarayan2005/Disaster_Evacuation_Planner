"""
Lightweight admin auth for the admin dashboard — deliberately simple
(no external auth library needed, nothing new added to requirements.txt):

  - passwords hashed with PBKDF2-HMAC-SHA256 (stdlib hashlib, salted)
  - successful login gets a random opaque session token, held in an
    in-memory dict with an expiry

This is fine for a single-process local/dev deployment (matches the
rest of this project's scope) but won't survive a server restart or
work across multiple worker processes — swap in Redis-backed sessions
or a real JWT library first if this ever goes into a real production
deployment with multiple admins/instances.
"""
import hashlib
import hmac
import os
import secrets
import time

from sqlalchemy import text
from sqlalchemy.orm import Session

PBKDF2_ITERATIONS = 260_000
SESSION_TTL_SECONDS = 8 * 60 * 60  # 8 hours

# token -> (username, expires_at_epoch_seconds)
_active_sessions: dict[str, tuple[str, float]] = {}


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, digest_hex = password_hash.split("$", 1)
    except ValueError:
        return False
    expected = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return hmac.compare_digest(expected.hex(), digest_hex)


def authenticate_admin(db: Session, username: str, password: str) -> str | None:
    """Returns a fresh session token if the credentials are valid, else None."""
    row = db.execute(text("""
        SELECT username, password_hash FROM admin_users WHERE username = :username
    """), {"username": username}).mappings().first()

    if row is None or not verify_password(password, row["password_hash"]):
        return None

    token = secrets.token_urlsafe(32)
    _active_sessions[token] = (row["username"], time.time() + SESSION_TTL_SECONDS)
    return token


def resolve_session(token: str) -> str | None:
    """Returns the admin username for a valid, unexpired token, else None."""
    session = _active_sessions.get(token)
    if session is None:
        return None
    username, expires_at = session
    if time.time() > expires_at:
        _active_sessions.pop(token, None)
        return None
    return username


def revoke_session(token: str) -> None:
    _active_sessions.pop(token, None)
