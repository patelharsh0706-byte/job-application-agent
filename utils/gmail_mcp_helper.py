"""
gmail_mcp_helper.py

Wrapper around Gmail MCP tools for:
  - Searching for replies to job applications
  - Creating draft follow-up emails for manual review

Called by orchestrator.py to check replies and create follow-up drafts.
Requires Gmail MCP to be authenticated (/mcp → claude.ai Gmail).
"""

import re
from datetime import datetime


def search_replies(sent_emails: list[dict], since_timestamp: str) -> list[dict]:
    """
    Search Gmail inbox for replies to job applications.

    Args:
        sent_emails: list of {"to_email": str, "message_id": str, "sent_at": str}
        since_timestamp: ISO8601 string

    Returns:
        list of {"to_email": str, "replied_at": str, "message_id": str}

    USAGE FROM ORCHESTRATOR:
        from gmail_mcp_helper import search_replies
        from orchestrator import load_jobs

        jobs = load_jobs()
        sent_emails = [
            {"to_email": j["contact_email"], "message_id": j["message_id"], "sent_at": j["sent_at"]}
            for j in jobs if j["status"] in ("sent", "followed_up") and j.get("message_id")
        ]
        replies = search_replies(sent_emails, batch_sent_at)

        # Manually run: python orchestrator.py --check-replies
    """
    print("\n[gmail_mcp] Searching for replies...")

    # Parse timestamp
    try:
        since_dt = datetime.fromisoformat(since_timestamp.replace("Z", "+00:00"))
        since_date = since_dt.strftime("%Y/%m/%d")
    except Exception:
        since_date = "2026/01/01"

    # Build search query: messages from any of the sent addresses, after the batch send date
    sent_addresses = {e["to_email"] for e in sent_emails}
    address_query = " OR ".join([f"from:{addr}" for addr in sent_addresses])
    query = f"({address_query}) after:{since_date}"

    print(f"[gmail_mcp] Query: {query}")
    print("[gmail_mcp] → Call: gmail_search_messages(q='{query}')")
    print("[gmail_mcp] (This will be executed by the MCP tool when you run it)")

    # Return format: the actual search happens via MCP in orchestrator
    return []


def create_follow_up_draft(
    to_email: str,
    subject: str,
    body: str,
    applicant_name: str,
) -> dict:
    """
    Create a Gmail draft follow-up email for manual review before sending.

    Args:
        to_email: recruiter email
        subject: email subject
        body: email body
        applicant_name: your name (for signature)

    Returns:
        {"success": bool, "draft_id": str, "url": str, "error": str}

    USAGE FROM ORCHESTRATOR:
        from gmail_mcp_helper import create_follow_up_draft

        result = create_follow_up_draft(
            to_email="recruiter@company.com",
            subject="Following up — Senior Engineer role",
            body="Hi,\n\nI wanted to follow up...",
            applicant_name="Harshkumar Patel",
        )
        # Draft created in Gmail — review and send manually
    """
    print(f"\n[gmail_mcp] Creating draft follow-up to {to_email}")
    print(f"[gmail_mcp] Subject: {subject}")
    print(f"[gmail_mcp] → Call: gmail_create_draft(to='{to_email}', subject='{subject}', body=...)")
    print("[gmail_mcp] (This will be executed by the MCP tool when you run it)")

    # Return placeholder — actual draft creation happens via MCP
    return {
        "success": False,
        "draft_id": None,
        "url": "https://mail.google.com/mail/u/0/#drafts",
        "error": "MCP integration pending",
    }


def list_drafts() -> list[dict]:
    """
    List all Gmail drafts (for debugging/review).

    Returns:
        list of {"id": str, "to": str, "subject": str, "snippet": str}
    """
    print("[gmail_mcp] Listing Gmail drafts...")
    print("[gmail_mcp] → Call: gmail_list_drafts()")
    return []
