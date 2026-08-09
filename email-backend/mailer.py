"""
Send emails via SMTP from admin@infinet.services.
Env: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, FROM_EMAIL (default admin@infinet.services).
HTML templates use InfiNet UI theme: purple (#8b6bab, #6b4b8a), blue (#5b9bd5), dark (#0a0a0f, #16161e).
"""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

FROM_EMAIL = os.getenv("FROM_EMAIL", "admin@infinet.services")

# InfiNet theme (matches assets_ui.py / UI)
THEME = {
    "bg": "#0a0a0f",
    "card": "#16161e",
    "border": "#2a2340",
    "purple": "#6b4b8a",
    "purple_light": "#8b6bab",
    "blue": "#5b9bd5",
    "text": "#e0e0e0",
    "muted": "#888888",
    "footer": "#6b6b80",
}


def _smtp():
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", FROM_EMAIL)
    password = os.getenv("SMTP_PASSWORD", "")
    if not host or not password:
        return None
    return host, port, user, password


def _html_wrapper(body_content: str, title: str) -> str:
    """Wrap content in InfiNet-themed email layout (inline styles for email clients)."""
    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
</head>
<body style="margin:0; padding:0; background-color:{THEME["bg"]}; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:{THEME["bg"]}; min-height:100vh;">
    <tr>
      <td align="center" style="padding: 32px 16px;">
        <table role="presentation" width="100%" style="max-width: 480px; background-color:{THEME["card"]}; border: 1px solid {THEME["border"]}; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
          <tr>
            <td style="padding: 28px 24px; border-bottom: 1px solid {THEME["border"]};">
              <h1 style="margin:0; font-size: 22px; font-weight: 600; color:{THEME["purple_light"]}; text-align: center;">InfiNet</h1>
              <p style="margin: 6px 0 0 0; font-size: 13px; color:{THEME["muted"]}; text-align: center;">Dark Web OSINT Tool</p>
            </td>
          </tr>
          <tr>
            <td style="padding: 28px 24px; color:{THEME["text"]}; font-size: 15px; line-height: 1.5;">
              {body_content}
            </td>
          </tr>
          <tr>
            <td style="padding: 16px 24px; border-top: 1px solid {THEME["border"]}; font-size: 12px; color:{THEME["footer"]}; text-align: center;">
              Powered by Robin • Modified by InfiNet
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def send_email(to: str, subject: str, body_text: str, body_html: str | None = None) -> bool:
    """Send email. Returns True on success."""
    cfg = _smtp()
    if not cfg:
        return False
    host, port, user, password = cfg
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = to
    msg.attach(MIMEText(body_text, "plain"))
    if body_html:
        msg.attach(MIMEText(body_html, "html"))
    try:
        with smtplib.SMTP(host, port) as s:
            s.starttls()
            s.login(user, password)
            s.sendmail(FROM_EMAIL, [to], msg.as_string())
        return True
    except Exception:
        return False


def send_signup_code(to: str, code: str) -> bool:
    subject = "Your InfiNet signup verification code"
    text = "Your verification code is: " + code + "\n\nIt expires in 15 minutes.\n\n— InfiNet"
    body = f"""
              <p style="margin:0 0 16px 0;">Your verification code is:</p>
              <p style="margin:0 0 20px 0; font-size: 28px; font-weight: 700; letter-spacing: 6px; color:{THEME["blue"]}; text-align: center;">{code}</p>
              <p style="margin:0; color:{THEME["muted"]}; font-size: 14px;">This code expires in 15 minutes.</p>
            """
    html = _html_wrapper(body.strip(), "Verification code – InfiNet")
    return send_email(to, subject, text, html)


def send_reset_link(to: str, reset_url: str) -> bool:
    subject = "Reset your InfiNet password"
    text = "Click the link below to reset your password:\n\n" + reset_url + "\n\nThis link expires in 1 hour.\n\n— InfiNet"
    body = f"""
              <p style="margin:0 0 16px 0;">Click the button below to reset your password:</p>
              <p style="margin:0 0 24px 0; text-align: center;">
                <a href="{reset_url}" style="display: inline-block; padding: 12px 24px; background: linear-gradient(135deg, {THEME["purple"]} 0%, #4a3560 100%); color: #fff; text-decoration: none; font-weight: 600; border-radius: 8px; border: 1px solid {THEME["purple_light"]}; font-size: 15px;">Reset password</a>
              </p>
              <p style="margin:0 0 8px 0; color:{THEME["muted"]}; font-size: 14px;">Or copy this link:</p>
              <p style="margin:0; word-break: break-all;"><a href="{reset_url}" style="color:{THEME["blue"]}; text-decoration: none;">{reset_url}</a></p>
              <p style="margin: 20px 0 0 0; color:{THEME["muted"]}; font-size: 14px;">This link expires in 1 hour.</p>
            """
    html = _html_wrapper(body.strip(), "Reset password – InfiNet")
    return send_email(to, subject, text, html)
