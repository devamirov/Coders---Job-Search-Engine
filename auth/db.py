"""
SQLite-backed store for users, usage, subscriptions, and WhatsApp verification.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import bcrypt

# Default DB path (server data dir)
DATA_DIR = Path(os.getenv("ROBIN_DATA_DIR", "/app/data"))
DB_PATH = DATA_DIR / "robin_infinet.db"

# Plan limits: free = 3 total searches per user (lifetime, no monthly renewal); unlimited = no cap; lifetime = no cap forever
FREE_LIMIT = 3
PLANS = {
    "free": FREE_LIMIT,
    "unlimited": 999999,  # $19/mo — active subscription required
    "lifetime": 999999,   # $149 one-time — permanently unlocks (never expires)
}


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


def _init_schema(c: sqlite3.Connection) -> None:
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            google_id TEXT UNIQUE,
            whatsapp TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            period TEXT NOT NULL,
            search_count INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, period),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            cryptomus_payment_id TEXT,
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS verification_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            phone TEXT NOT NULL,
            code TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'USD',
            payment_id TEXT NOT NULL,
            order_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS last_search (
            user_id INTEGER PRIMARY KEY,
            original_query TEXT NOT NULL,
            refined_query TEXT NOT NULL,
            summary_markdown TEXT NOT NULL,
            result_count INTEGER NOT NULL DEFAULT 0,
            filtered_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_usage_user_period ON usage(user_id, period);
        CREATE INDEX IF NOT EXISTS idx_subs_user ON subscriptions(user_id);
        CREATE INDEX IF NOT EXISTS idx_payments_payment_id ON payments(payment_id);
    """)


def init_db() -> None:
    with _conn() as c:
        _init_schema(c)


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _check_password(password: str, hash_: str) -> bool:
    return bcrypt.checkpw(password.encode(), hash_.encode())


def _period() -> str:
    """Current calendar month YYYY-MM."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def user_create(email: str, password: str) -> dict[str, Any]:
    with _conn() as c:
        init_db()
        h = _hash_password(password)
        cur = c.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (email.strip().lower(), h),
        )
        uid = cur.lastrowid
        period = _period()
        c.execute(
            "INSERT INTO usage (user_id, period, search_count) VALUES (?, ?, 0)",
            (uid, period),
        )
    return user_by_id(uid)


def user_create_google(email: str, google_id: str) -> dict[str, Any]:
    """Create user for Google sign-in (no password)."""
    with _conn() as c:
        init_db()
        email_clean = email.strip().lower()
        cur = c.execute(
            "INSERT INTO users (email, password_hash, google_id) VALUES (?, NULL, ?)",
            (email_clean, google_id),
        )
        uid = cur.lastrowid
        period = _period()
        c.execute(
            "INSERT INTO usage (user_id, period, search_count) VALUES (?, ?, 0)",
            (uid, period),
        )
    return user_by_id(uid)


def user_by_id(uid: int) -> Optional[dict[str, Any]]:
    with _conn() as c:
        r = c.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        return dict(r) if r else None


def user_by_email(email: str) -> Optional[dict[str, Any]]:
    with _conn() as c:
        r = c.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        return dict(r) if r else None


def user_by_google_id(google_id: str) -> Optional[dict[str, Any]]:
    with _conn() as c:
        r = c.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()
        return dict(r) if r else None


def user_login(email: str, password: str) -> Optional[dict[str, Any]]:
    u = user_by_email(email)
    if not u or not u.get("password_hash"):
        return None
    if not _check_password(password, u["password_hash"]):
        return None
    return u


def user_link_google(uid: int, google_id: str) -> None:
    with _conn() as c:
        c.execute("UPDATE users SET google_id = ? WHERE id = ?", (google_id, uid))


def user_phone_taken(phone: str, exclude_uid: Optional[int] = None) -> bool:
    """True if this phone is already linked to another user. One number = one account."""
    phone = (phone or "").strip()
    if not phone:
        return False
    with _conn() as c:
        if exclude_uid is not None:
            r = c.execute("SELECT id FROM users WHERE whatsapp = ? AND id != ?", (phone, exclude_uid)).fetchone()
        else:
            r = c.execute("SELECT id FROM users WHERE whatsapp = ?", (phone,)).fetchone()
    return r is not None


def user_set_whatsapp(uid: int, phone: str) -> bool:
    """Set user's WhatsApp number. Returns False if this number is already linked to another account (one phone per user)."""
    phone = (phone or "").strip()
    if not phone:
        return False
    with _conn() as c:
        other = c.execute("SELECT id FROM users WHERE whatsapp = ? AND id != ?", (phone, uid)).fetchone()
        if other:
            return False
        c.execute("UPDATE users SET whatsapp = ? WHERE id = ?", (phone, uid))
    return True


def user_set_password(email: str, new_password: str) -> bool:
    """Update password for user by email. Returns True if user exists and was updated."""
    u = user_by_email(email)
    if not u:
        return False
    h = _hash_password(new_password)
    with _conn() as c:
        c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (h, u["id"]))
    return True


def usage_get(user_id: int) -> tuple[int, int, str]:
    """Returns (used, limit, plan). Free plan: used = total searches ever (no monthly reset), limit = 3."""
    plan = "free"
    sub = subscription_active(user_id)
    if sub:
        plan = (sub.get("plan") or "free").strip().lower()
    limit = PLANS.get(plan, FREE_LIMIT)
    with _conn() as c:
        # If user is back on free after a paid subscription expired, mark expired and restore pre-upgrade usage count
        if plan == "free":
            expired_sub = c.execute(
                "SELECT id FROM subscriptions WHERE user_id = ? AND status = 'active' AND ends_at <= datetime('now') LIMIT 1",
                (user_id,),
            ).fetchone()
            if expired_sub:
                c.execute("DELETE FROM usage WHERE user_id = ?", (user_id,))
                c.execute(
                    "INSERT INTO usage (user_id, period, search_count) VALUES (?, 'pre_upgrade', ?)",
                    (user_id, FREE_LIMIT),
                )
                c.execute("UPDATE subscriptions SET status = 'expired' WHERE user_id = ? AND status = 'active' AND ends_at <= datetime('now')", (user_id,))
        r = c.execute(
            "SELECT COALESCE(SUM(search_count), 0) AS total FROM usage WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        used = int(r["total"]) if r else 0
    return used, limit, plan


def usage_increment(user_id: int) -> None:
    period = _period()
    with _conn() as c:
        c.execute(
            """
            INSERT INTO usage (user_id, period, search_count) VALUES (?, ?, 1)
            ON CONFLICT(user_id, period) DO UPDATE SET search_count = search_count + 1
            """,
            (user_id, period),
        )


def subscription_active(user_id: int) -> Optional[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        r = c.execute(
            """
            SELECT * FROM subscriptions
            WHERE user_id = ? AND status = 'active' AND ends_at > ?
            ORDER BY ends_at DESC LIMIT 1
            """,
            (user_id, now),
        ).fetchone()
    return dict(r) if r else None


def subscription_create(user_id: int, plan: str, cryptomus_payment_id: Optional[str] = None) -> dict[str, Any]:
    """Create a subscription. Plan: unlimited ($19/mo, 30 days) or lifetime ($149 one-time, never expires)."""
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    if plan == "lifetime":
        # Lifetime: never expires (far-future ends_at)
        ends = datetime(2099, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    else:
        ends = now + timedelta(days=30)
    with _conn() as c:
        cur = c.execute(
            """
            INSERT INTO subscriptions (user_id, plan, status, cryptomus_payment_id, starts_at, ends_at)
            VALUES (?, ?, 'active', ?, ?, ?)
            """,
            (user_id, plan, cryptomus_payment_id or "", now.isoformat(), ends.isoformat()),
        )
        sid = cur.lastrowid
    with _conn() as c:
        r = c.execute("SELECT * FROM subscriptions WHERE id = ?", (sid,)).fetchone()
    return dict(r)


def payment_create(user_id: int, plan: str, amount: float, currency: str, payment_id: str, order_id: str) -> None:
    """Store a pending Cryptomus payment."""
    with _conn() as c:
        _init_schema(c)
        c.execute(
            """
            INSERT INTO payments (user_id, plan, amount, currency, payment_id, order_id, status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (user_id, plan, amount, currency, payment_id, order_id),
        )


def payment_by_payment_id(payment_id: str) -> Optional[dict[str, Any]]:
    """Get payment by Cryptomus uuid (payment_id)."""
    with _conn() as c:
        r = c.execute("SELECT * FROM payments WHERE payment_id = ?", (payment_id,)).fetchone()
        return dict(r) if r else None


def payment_update_status(payment_id: str, status: str) -> bool:
    """Update payment status. Returns True if row was updated."""
    with _conn() as c:
        cur = c.execute("UPDATE payments SET status = ? WHERE payment_id = ?", (status, payment_id))
        return cur.rowcount > 0


def verification_code_create(user_id: int, phone: str) -> str:
    """Create a 6-digit code, store it, return it. (In production, send via WhatsApp.)"""
    code = "".join(secrets.choice("0123456789") for _ in range(6))
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    expires = now + timedelta(minutes=10)
    with _conn() as c:
        c.execute(
            "INSERT INTO verification_codes (user_id, phone, code, expires_at) VALUES (?, ?, ?, ?)",
            (user_id, phone, code, expires.isoformat()),
        )
    return code


def verification_code_verify(user_id: int, phone: str, code: str) -> tuple[bool, str | None]:
    """Verify code and link phone to user. Returns (True, None) on success, (False, reason) otherwise.
    reason: 'invalid_code' or 'phone_taken' (so UI can show the right message)."""
    now = datetime.now(timezone.utc).isoformat()
    phone = (phone or "").strip()
    code = (code or "").strip()
    with _conn() as c:
        r = c.execute(
            """
            SELECT id FROM verification_codes
            WHERE user_id = ? AND phone = ? AND code = ? AND expires_at > ? AND used = 0
            """,
            (user_id, phone, code, now),
        ).fetchone()
    if not r:
        return False, "invalid_code"
    # Anti-cheat: one phone per user – reject if already linked to another account
    with _conn() as c:
        other = c.execute("SELECT id FROM users WHERE whatsapp = ? AND id != ?", (phone, user_id)).fetchone()
        if other:
            return False, "phone_taken"
    with _conn() as c:
        c.execute("UPDATE verification_codes SET used = 1 WHERE id = ?", (r["id"],))
    if not user_set_whatsapp(user_id, phone):
        return False, "phone_taken"
    return True, None


def last_search_save(
    user_id: int,
    original_query: str,
    refined_query: str,
    summary_markdown: str,
    result_count: int = 0,
    filtered_count: int = 0,
) -> None:
    """Store or replace the last completed search for this user (one per user)."""
    with _conn() as c:
        c.execute(
            """
            INSERT INTO last_search (user_id, original_query, refined_query, summary_markdown, result_count, filtered_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                original_query = excluded.original_query,
                refined_query = excluded.refined_query,
                summary_markdown = excluded.summary_markdown,
                result_count = excluded.result_count,
                filtered_count = excluded.filtered_count,
                created_at = datetime('now')
            """,
            (user_id, (original_query or "").strip(), (refined_query or "").strip(), summary_markdown or "", result_count, filtered_count),
        )


def last_search_get(user_id: int) -> Optional[dict[str, Any]]:
    """Return the last saved search for this user, or None."""
    with _conn() as c:
        r = c.execute("SELECT * FROM last_search WHERE user_id = ?", (user_id,)).fetchone()
        return dict(r) if r else None
