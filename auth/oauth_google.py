"""
Google OAuth login. Configure via env: GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET.
"""
from __future__ import annotations

import os
import urllib.request
import urllib.parse
import json
from typing import Any, Optional

GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")

TOKEN_URI = "https://oauth2.googleapis.com/token"
USERINFO_URI = "https://www.googleapis.com/oauth2/v2/userinfo"


def auth_url(redirect_uri: str, state: str) -> str:
    """Google OAuth authorization URL."""
    if not GOOGLE_OAUTH_CLIENT_ID:
        return ""
    base = "https://accounts.google.com/o/oauth2/v2/auth"
    params = (
        f"client_id={GOOGLE_OAUTH_CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
        "&response_type=code"
        "&scope=openid%20email%20profile"
        f"&state={state}"
    )
    return f"{base}?{params}"


def exchange_code(code: str, redirect_uri: str) -> Optional[dict[str, Any]]:
    """Exchange code for tokens and fetch user info. Returns { sub, email } or None."""
    if not GOOGLE_OAUTH_CLIENT_ID or not GOOGLE_OAUTH_CLIENT_SECRET:
        return None
    try:
        body = urllib.parse.urlencode({
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
            "grant_type": "authorization_code",
        }).encode("utf-8")
        req = urllib.request.Request(
            TOKEN_URI,
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        access_token = data.get("access_token")
        if not access_token:
            return None
        # Fetch user info
        req2 = urllib.request.Request(
            USERINFO_URI,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(req2, timeout=10) as resp2:
            user_data = json.loads(resp2.read().decode())
        return {
            "sub": user_data.get("id"),
            "email": (user_data.get("email") or "").strip().lower(),
        }
    except Exception:
        return None
