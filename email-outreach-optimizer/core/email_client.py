"""
email_client.py — Fixed, read-only. Do not modify.

Abstraction layer for email sending and reply tracking.
Plug in Purands (or any other provider) credentials via environment variables.

Environment variables required:
    EMAIL_PROVIDER      — "purands", "smtp", or "sendgrid"
    SENDER_EMAIL        — from address
    SENDER_NAME         — display name
    SENDER_TITLE        — job title (used in email signature)
    SENDER_COMPANY      — company name (used in email signature)

    For Purands:
        PURANDS_API_KEY     — API key (to be provided)
        PURANDS_API_URL     — base API URL (to be provided)

    For SMTP fallback:
        SMTP_HOST
        SMTP_PORT
        SMTP_USER
        SMTP_PASSWORD
        IMAP_HOST           — for reply checking
        IMAP_USER
        IMAP_PASSWORD
"""

import os
import imaplib
import email as email_lib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import Optional
import re


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def send_email(to_email: str, subject: str, body: str) -> dict:
    """
    Send a single email. Returns a result dict:
        {"success": bool, "message_id": str | None, "error": str | None}
    """
    provider = os.environ.get("EMAIL_PROVIDER", "smtp").lower()
    if provider == "purands":
        return _send_via_purands(to_email, subject, body)
    elif provider == "sendgrid":
        return _send_via_sendgrid(to_email, subject, body)
    else:
        return _send_via_smtp(to_email, subject, body)


def check_replies(sent_emails: list[dict], since_timestamp: str) -> list[dict]:
    """
    Check for replies to previously sent emails.

    Args:
        sent_emails: list of {"to_email": str, "message_id": str, "sent_at": str}
        since_timestamp: ISO8601 string — only check replies after this time

    Returns:
        list of {"to_email": str, "replied_at": str, "message_id": str}
    """
    provider = os.environ.get("EMAIL_PROVIDER", "smtp").lower()
    if provider == "purands":
        return _check_replies_purands(sent_emails, since_timestamp)
    else:
        return _check_replies_imap(sent_emails, since_timestamp)


# ---------------------------------------------------------------------------
# Purands integration (stub — fill in when API credentials are available)
# ---------------------------------------------------------------------------

def _send_via_purands(to_email: str, subject: str, body: str) -> dict:
    """
    TODO: Implement once Purands API credentials and endpoint docs are provided.

    Expected API shape (placeholder — update to match actual Purands API):
        POST {PURANDS_API_URL}/messages/send
        Headers: Authorization: Bearer {PURANDS_API_KEY}
        Body: {
            "from": SENDER_EMAIL,
            "to": to_email,
            "subject": subject,
            "text": body
        }
    """
    import requests

    api_key = os.environ["PURANDS_API_KEY"]
    api_url = os.environ["PURANDS_API_URL"].rstrip("/")
    sender = os.environ["SENDER_EMAIL"]

    resp = requests.post(
        f"{api_url}/messages/send",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"from": sender, "to": to_email, "subject": subject, "text": body},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "success": True,
        "message_id": data.get("message_id") or data.get("id"),
        "error": None,
    }


def _check_replies_purands(sent_emails: list[dict], since_timestamp: str) -> list[dict]:
    """
    TODO: Implement once Purands API credentials and endpoint docs are provided.

    Expected API shape (placeholder — update to match actual Purands API):
        GET {PURANDS_API_URL}/messages/replies?since={since_timestamp}
    """
    import requests

    api_key = os.environ["PURANDS_API_KEY"]
    api_url = os.environ["PURANDS_API_URL"].rstrip("/")

    resp = requests.get(
        f"{api_url}/messages/replies",
        headers={"Authorization": f"Bearer {api_key}"},
        params={"since": since_timestamp},
        timeout=15,
    )
    resp.raise_for_status()
    reply_records = resp.json().get("replies", [])

    sent_ids = {e["message_id"] for e in sent_emails}
    sent_addresses = {e["to_email"].lower() for e in sent_emails}

    replies = []
    for r in reply_records:
        from_addr = r.get("from", "").lower()
        in_reply_to = r.get("in_reply_to", "")
        if in_reply_to in sent_ids or from_addr in sent_addresses:
            replies.append({
                "to_email": from_addr,
                "replied_at": r.get("received_at", ""),
                "message_id": r.get("id", ""),
            })
    return replies


# ---------------------------------------------------------------------------
# SendGrid integration
# ---------------------------------------------------------------------------

def _send_via_sendgrid(to_email: str, subject: str, body: str) -> dict:
    import requests

    api_key = os.environ["SENDGRID_API_KEY"]
    sender = os.environ["SENDER_EMAIL"]
    sender_name = os.environ.get("SENDER_NAME", sender)

    resp = requests.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": sender, "name": sender_name},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
        },
        timeout=15,
    )
    resp.raise_for_status()
    message_id = resp.headers.get("X-Message-Id")
    return {"success": True, "message_id": message_id, "error": None}


# ---------------------------------------------------------------------------
# SMTP fallback
# ---------------------------------------------------------------------------

def _send_via_smtp(to_email: str, subject: str, body: str) -> dict:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", 587))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    sender = os.environ["SENDER_EMAIL"]
    sender_name = os.environ.get("SENDER_NAME", sender)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{sender_name} <{sender}>"
    msg["To"] = to_email
    msg["Message-ID"] = _make_message_id(sender)
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(sender, [to_email], msg.as_string())

    return {"success": True, "message_id": msg["Message-ID"], "error": None}


def _check_replies_imap(sent_emails: list[dict], since_timestamp: str) -> list[dict]:
    host = os.environ["IMAP_HOST"]
    user = os.environ["IMAP_USER"]
    password = os.environ["IMAP_PASSWORD"]
    sender = os.environ["SENDER_EMAIL"]

    since_dt = datetime.fromisoformat(since_timestamp.replace("Z", "+00:00"))
    imap_date = since_dt.strftime("%d-%b-%Y")

    sent_addresses = {e["to_email"].lower() for e in sent_emails}
    sent_ids = {e["message_id"] for e in sent_emails if e.get("message_id")}

    replies = []
    with imaplib.IMAP4_SSL(host) as imap:
        imap.login(user, password)
        imap.select("INBOX")
        _, data = imap.search(None, f'(TO "{sender}" SINCE {imap_date})')
        for num in data[0].split():
            _, msg_data = imap.fetch(num, "(RFC822)")
            msg = email_lib.message_from_bytes(msg_data[0][1])
            from_addr = email_lib.utils.parseaddr(msg.get("From", ""))[1].lower()
            in_reply_to = msg.get("In-Reply-To", "").strip()
            date_str = msg.get("Date", "")
            if from_addr in sent_addresses or in_reply_to in sent_ids:
                replies.append({
                    "to_email": from_addr,
                    "replied_at": date_str,
                    "message_id": msg.get("Message-ID", ""),
                })

    return replies


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def render_template(template: str, variables: dict) -> str:
    """Replace {{variable}} placeholders in template with values."""
    result = template
    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", str(value))
    return result


def _make_message_id(sender_email: str) -> str:
    domain = sender_email.split("@")[-1] if "@" in sender_email else "localhost"
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    return f"<{ts}.optimizer@{domain}>"
