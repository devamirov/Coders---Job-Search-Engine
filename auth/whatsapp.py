"""
WhatsApp verification code delivery for spectre.guru.
Uses the same WhatsApp verification server as AI (via spectre-email-backend proxy).
Configure: BASE_URL (e.g. https://spectre.guru). Backend proxies to WHATSAPP_VERIFICATION_URL (default 127.0.0.1:3006).
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Tuple

BASE_URL = (os.getenv("BASE_URL") or "http://localhost:8501").rstrip("/")
BACKEND_SEND_URL = f"{BASE_URL}/api/send-whatsapp-verification"


def send_code(phone: str, code: str) -> Tuple[bool, str]:
    """Send verification code via WhatsApp (same number as AI: +4915754575150). Returns (True, '') if sent, else (False, error_message)."""
    phone = (phone or "").strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not phone or not code:
        return False, "Phone and code required"
    if not phone.startswith("+"):
        return False, "Phone must be E.164 (e.g. +4915754575150)"
    try:
        body = json.dumps({"phone_number": phone, "code": code}).encode()
        req = urllib.request.Request(
            BACKEND_SEND_URL,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        if data.get("ok") is True:
            return True, ""
        return False, (data.get("error") or "Failed to send")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode())
            msg = err.get("error", str(e))
        except Exception:
            msg = str(e)
        return False, msg
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return False, str(e)
