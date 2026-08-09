"""
Cryptomus payment gateway integration for spectre.guru.
Same merchant/API as ai.infinet.services; webhook URL is per payment (url_callback).
Configure via env: CRYPTOMUS_API_KEY, CRYPTOMUS_MERCHANT_ID.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.request
from typing import Any, Optional

CRYPTOMUS_API_KEY = os.getenv("CRYPTOMUS_API_KEY", "")
CRYPTOMUS_MERCHANT_ID = os.getenv("CRYPTOMUS_MERCHANT_ID", "")
CRYPTOMUS_API_URL = "https://api.cryptomus.com/v1"

PLAN_AMOUNTS = {"unlimited": 19.0, "lifetime": 149.0}
PLAN_CURRENCIES = {"unlimited": "USD", "lifetime": "USD"}


def _sign_create(data: dict[str, Any]) -> str:
    """Signature for payment creation: MD5(base64(JSON) + apiKey), no slash escaping."""
    payload = json.dumps(data, separators=(",", ":"))
    b64 = base64.b64encode(payload.encode()).decode()
    return hashlib.md5((b64 + CRYPTOMUS_API_KEY).encode()).hexdigest()


def create_payment(
    user_id: int,
    plan: str,
    email: str,
    return_url: str,
    cancel_url: str,
    callback_url: str,
) -> Optional[dict[str, Any]]:
    """Create a Cryptomus payment. Returns { payment_url, uuid, order_id } or None."""
    if not CRYPTOMUS_API_KEY or not CRYPTOMUS_MERCHANT_ID:
        return None
    amount = PLAN_AMOUNTS.get(plan)
    if amount is None:
        return None
    currency = PLAN_CURRENCIES.get(plan, "USD")
    order_id = f"spectre_{user_id}_{int(time.time())}"
    payment_data = {
        "amount": str(amount),
        "currency": currency,
        "order_id": order_id,
        "url_return": return_url,
        "url_callback": callback_url,
        "is_payment_multiple": False,
        "lifetime": 7200,
        "additional_data": json.dumps({"user_id": user_id, "plan": plan}),
    }
    # Sign the exact body we send (Cryptomus: sign = MD5(base64(body) + API_KEY))
    body_str = json.dumps(payment_data, separators=(",", ":"))
    signature = hashlib.md5((base64.b64encode(body_str.encode()).decode() + CRYPTOMUS_API_KEY).encode()).hexdigest()
    body = body_str.encode()
    req = urllib.request.Request(
        f"{CRYPTOMUS_API_URL}/payment",
        data=body,
        method="POST",
        headers={
            "merchant": CRYPTOMUS_MERCHANT_ID,
            "sign": signature,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        result = data.get("result")
        if not result:
            return None
        return {
            "payment_url": result.get("url"),
            "uuid": result.get("uuid"),
            "order_id": order_id,
        }
    except Exception:
        return None


def verify_webhook(payload: dict, signature: str) -> bool:
    """Verify Cryptomus webhook signature (slash-escaped JSON, base64, MD5). Used by webhook endpoint."""
    if not CRYPTOMUS_API_KEY:
        return False
    sign_received = payload.get("sign")
    if not sign_received:
        return False
    data_copy = {k: v for k, v in payload.items() if k != "sign"}
    payload_str = json.dumps(data_copy, separators=(",", ":"))
    payload_str = payload_str.replace("/", "\\/")
    b64 = base64.b64encode(payload_str.encode()).decode()
    expected = hashlib.md5((b64 + CRYPTOMUS_API_KEY).encode()).hexdigest()
    return sign_received == expected


def handle_webhook(payload: dict) -> Optional[tuple[int, str]]:
    """Parse webhook payload. Returns (user_id, plan) if payment succeeded; caller updates DB."""
    status = payload.get("status")
    if status not in ("paid", "paid_over"):
        return None
    order_id = payload.get("order_id") or ""
    if not order_id.startswith("spectre_"):
        return None
    try:
        add = json.loads(payload.get("additional_data") or "{}")
        uid = add.get("user_id")
        plan = add.get("plan")
        if uid is not None and plan:
            return (int(uid), plan)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return None
