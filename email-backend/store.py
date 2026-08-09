"""
SQLite store for signup verification codes and password-reset tokens.
Separate from Robin app DB; lives under this backend's data dir.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_DIR = Path(os.getenv("EMAIL_BACKEND_DATA_DIR", "/var/www/spectre.guru/data"))
DB_PATH = DATA_DIR / "email_backend.db"


@contextmanager
def _conn():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db(c: sqlite3.Connection) -> None:
    c.executescript("""
        CREATE TABLE IF NOT EXISTS signup_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            code TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_signup_email ON signup_codes(email);
        CREATE INDEX IF NOT EXISTS idx_reset_token ON reset_tokens(token);
    """)


def create_signup_code(email: str) -> str:
    """Create 6-digit code for signup, store and return it."""
    code = "".join(secrets.choice("0123456789") for _ in range(6))
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=15)
    with _conn() as c:
        init_db(c)
        c.execute(
            "INSERT INTO signup_codes (email, code, expires_at) VALUES (?, ?, ?)",
            (email.strip().lower(), code, expires.isoformat()),
        )
    return code


def verify_signup_code(email: str, code: str) -> bool:
    """Verify signup code; delete it on success."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        r = c.execute(
            "SELECT id FROM signup_codes WHERE email = ? AND code = ? AND expires_at > ?",
            (email.strip().lower(), code.strip(), now),
        ).fetchone()
    if not r:
        return False
    with _conn() as c:
        c.execute("DELETE FROM signup_codes WHERE id = ?", (r["id"],))
    return True


def create_reset_token(email: str) -> str:
    """Create reset token, store and return it."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=1)
    with _conn() as c:
        init_db(c)
        # Invalidate any existing token for this email
        c.execute("DELETE FROM reset_tokens WHERE email = ?", (email.strip().lower(),))
        c.execute(
            "INSERT INTO reset_tokens (email, token, expires_at) VALUES (?, ?, ?)",
            (email.strip().lower(), token, expires.isoformat()),
        )
    return token


def verify_reset_token(token: str) -> str | None:
    """Verify reset token; return email if valid and delete token."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        r = c.execute(
            "SELECT id, email FROM reset_tokens WHERE token = ? AND expires_at > ?",
            (token.strip(), now),
        ).fetchone()
    if not r:
        return None
    email = r["email"]
    with _conn() as c:
        c.execute("DELETE FROM reset_tokens WHERE id = ?", (r["id"],))
    return email
