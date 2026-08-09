"""
Cryptomus payment gateway integration.
Configure via env: CRYPTOMUS_API_KEY, CRYPTOMUS_MERCHANT_ID, CRYPTOMUS_WEBHOOK_SECRET.
"""
from __future__ import annotations

import os
from typing import Any, Optional

# Placeholder until configs provided
CRYPTOMUS_API_KEY = os.getenv("CRYPTOMUS_API_KEY", "")
CRYPTOMUS_MERCHANT_ID = os.getenv("CRYPTOMUS_MERCHANT_ID", "")
CRYPTOMUS_WEBHOOK_SECRET = os.getenv("CRYPTOMUS_WEBHOOK_SECRET", "")

PLAN_AMOUNTS = {"unlimited": 19.0, "lifetime": 149.0}
PLAN_CURRENCIES = {"unlimited": "USD", "lifetime": "USD"}


def create_payment(user_id: int, plan: str, email: str, return_url: str, cancel_url: str) -> Optional[dict[str, Any]]:
    """Create a Cryptomus payment. Returns { payment_url, uuid } or None if not configured."""
    if not CRYPTOMUS_API_KEY or not CRYPTOMUS_MERCHANT_ID:
        return None
    amount = PLAN_AMOUNTS.get(plan)
    if amount is None:
        return None
    # TODO: implement actual Cryptomus API call when keys are provided
    return {"payment_url": "#", "uuid": "placeholder"}


def verify_webhook(payload: dict, signature: str) -> bool:
    """Verify Cryptomus webhook signature."""
    if not CRYPTOMUS_WEBHOOK_SECRET:
        return False
    # TODO: implement when config provided
    return False


def handle_webhook(payload: dict) -> Optional[tuple[int, str]]:
    """Process webhook. Returns (user_id, plan) if payment succeeded."""
    # TODO: parse payload, verify, create subscription
    return None
