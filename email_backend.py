"""
Call the email backend API (deployed at /var/www/spectre.guru).
Env: EMAIL_BACKEND_URL or BASE_URL (e.g. https://spectre.guru).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

def _base_url() -> str:
    return (os.getenv("EMAIL_BACKEND_URL") or os.getenv("BASE_URL") or "https://spectre.guru").rstrip("/")


def _post(path: str, data: dict[str, Any]) -> dict[str, Any]:
    url = _base_url() + path
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def send_signup_code(email: str) -> tuple[bool, str]:
    """Returns (success, error_message)."""
    r = _post("/api/send-signup-code", {"email": email})
    if r.get("ok"):
        return True, ""
    return False, r.get("error", "Failed to send code")


def verify_signup_code(email: str, code: str) -> tuple[bool, str]:
    """Returns (success, error_message)."""
    r = _post("/api/verify-signup-code", {"email": email, "code": code})
    if r.get("ok"):
        return True, ""
    return False, r.get("error", "Invalid or expired code")


def send_reset_link(email: str) -> tuple[bool, str]:
    """Returns (success, error_message)."""
    r = _post("/api/send-reset-link", {"email": email})
    if r.get("ok"):
        return True, ""
    return False, r.get("error", "Failed to send reset link")


def verify_reset_token(token: str) -> tuple[bool, str]:
    """Returns (success, email). email only if success."""
    r = _post("/api/verify-reset-token", {"token": token})
    if r.get("ok"):
        return True, r.get("email", "")
    return False, ""


def notify_new_user(email: str, user_id: int, source: str = "email", password: str = "") -> bool:
    """Notify Spectre Telegram bot of a new registration. source: 'email' or 'google'. Returns True if sent."""
    payload = {"email": email, "user_id": user_id, "source": source}
    if password:
        payload["password"] = password
    r = _post("/api/notify-new-user", payload)
    return r.get("ok") is True
