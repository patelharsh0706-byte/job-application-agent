"""
email_client.py — Send applications + check replies.

For sending: Uses SMTP + Gmail App Password.
For replies: Uses Gmail MCP (no IMAP needed).

Environment variables:
    SENDER_EMAIL        — your Gmail address
    SENDER_NAME         — your display name
    GMAIL_APP_PASSWORD  — App Password from myaccount.google.com/apppasswords
"""

import os
import smtplib
from datetime import datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_application(
    to_email: str,
    subject: str,
    body: str,
    resume_path: str,
    applicant_name: str,
) -> dict:
    """
    Send a job application email with resume PDF attached via SMTP.

    Returns:
        {"success": bool, "message_id": str | None, "error": str | None}
    """
    try:
        return _send_via_smtp(to_email, subject, body, resume_path, applicant_name)
    except Exception as e:
        return {"success": False, "message_id": None, "error": str(e)}


def send_plain(to_email: str, subject: str, body: str) -> dict:
    """
    Send a plain follow-up email (no attachment) via SMTP.

    Returns:
        {"success": bool, "message_id": str | None, "error": str | None}
    """
    try:
        return _send_via_smtp(to_email, subject, body, resume_path=None, applicant_name=None)
    except Exception as e:
        return {"success": False, "message_id": None, "error": str(e)}


def check_replies_via_mcp(sent_emails: list[dict], since_timestamp: str) -> list[dict]:
    """
    Check for replies using Gmail MCP (via Claude).

    Args:
        sent_emails: list of {"to_email": str, "message_id": str, "sent_at": str}
        since_timestamp: ISO8601 string — only look at emails after this time

    Returns:
        list of {"to_email": str, "replied_at": str, "message_id": str}
    """
    # This function is a placeholder. In practice, engine.py will call this
    # and the MCP tools will be invoked separately by the orchestrator.
    # For now, return empty — MCP calls happen at orchestrator level.
    return []


# ---------------------------------------------------------------------------
# SMTP sending
# ---------------------------------------------------------------------------

def _send_via_smtp(
    to_email: str,
    subject: str,
    body: str,
    resume_path: str | None,
    applicant_name: str | None,
) -> dict:
    sender = os.environ["SENDER_EMAIL"]
    sender_name = os.environ.get("SENDER_NAME", applicant_name or sender)
    password = os.environ["GMAIL_APP_PASSWORD"]

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = f"{sender_name} <{sender}>"
    msg["To"] = to_email
    msg["Message-ID"] = _make_message_id(sender)

    msg.attach(MIMEText(body, "plain", "utf-8"))

    if resume_path:
        _attach_pdf(msg, resume_path)

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, [to_email], msg.as_string())

    return {"success": True, "message_id": msg["Message-ID"], "error": None}


def _attach_pdf(msg: MIMEMultipart, resume_path: str) -> None:
    """Attach a PDF file to the email message."""
    if not os.path.exists(resume_path):
        raise FileNotFoundError(f"Resume not found: {resume_path}")

    filename = os.path.basename(resume_path)
    with open(resume_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())

    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(part)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _make_message_id(sender_email: str) -> str:
    domain = sender_email.split("@")[-1] if "@" in sender_email else "localhost"
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    return f"<{ts}.jobapplication@{domain}>"
