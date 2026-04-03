"""
orchestrator.py — Dashboard + daily reply checker.

Usage:
    python orchestrator.py              # show dashboard
    python orchestrator.py --check      # check Gmail for replies + auto-update jobs.csv
"""

import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ANSI colors
RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
DIM    = "\033[2m"
MAGENTA = "\033[95m"


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_json(filename: str) -> dict:
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def load_jobs() -> list[dict]:
    path = os.path.join(BASE_DIR, "jobs.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_jobs(jobs: list[dict]) -> None:
    path = os.path.join(BASE_DIR, "jobs.csv")
    fieldnames = [
        "id", "company", "role", "contact_email", "job_description_file",
        "variant_id", "status", "sent_at", "follow_up_at",
        "follow_up_sent_at", "replied_at", "message_id",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(jobs)


def load_results() -> list[dict]:
    path = os.path.join(BASE_DIR, "results.tsv")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Reply checking via Gmail MCP
# ---------------------------------------------------------------------------

def check_replies_and_update():
    """
    Search Gmail inbox for replies to sent applications.
    Update jobs.csv with reply status.
    Mark no-response jobs after 8 days (follow-up sent + 5 days with no reply).
    """
    jobs = load_jobs()
    active_jobs = [
        j for j in jobs
        if j["status"] in ("sent", "followed_up")
        and j.get("contact_email")
        and j.get("sent_at")
    ]

    if not active_jobs:
        print(f"\n{BOLD}[reply-check]{RESET} No active jobs to check.")
        return

    print(f"\n{BOLD}{'=' * 60}")
    print("  REPLY CHECK")
    print(f"{'=' * 60}{RESET}")
    print(f"  Checking {len(active_jobs)} active applications for replies...\n")

    # Build Gmail search query — look for replies from any sent company email
    sent_addresses = list({j["contact_email"].lower() for j in active_jobs})

    # Find the earliest sent_at for the search window
    earliest = min(j["sent_at"] for j in active_jobs if j.get("sent_at"))
    try:
        earliest_dt = datetime.fromisoformat(earliest.replace("Z", "+00:00"))
        since_date = earliest_dt.strftime("%Y/%m/%d")
    except Exception:
        since_date = "2026/04/01"

    address_query = " OR ".join([f"from:{addr}" for addr in sent_addresses])
    gmail_query = f"({address_query}) after:{since_date}"

    print(f"  {DIM}Gmail query: {gmail_query}{RESET}\n")
    print(f"  {YELLOW}→ Run this in Claude with Gmail MCP connected:{RESET}")
    print(f"  {CYAN}gmail_search_messages(q='{gmail_query}', maxResults=50){RESET}\n")

    # ── Auto no-response marking ──────────────────────────────────
    # Mark jobs as no_response if followed_up + 5 days have passed with no reply
    no_response_deadline_days = 5
    updated = []
    now_dt = now()

    for job in jobs:
        if job["status"] == "followed_up" and job.get("follow_up_sent_at"):
            try:
                fu_dt = datetime.fromisoformat(job["follow_up_sent_at"].replace("Z", "+00:00"))
                days_since_followup = (now_dt - fu_dt).days
                if days_since_followup >= no_response_deadline_days:
                    job["status"] = "no_response"
                    job["replied_at"] = ""
                    updated.append(job["company"] + " / " + job["role"])
            except Exception:
                pass

    if updated:
        save_jobs(jobs)
        print(f"  {RED}Marked {len(updated)} job(s) as no_response (no reply after follow-up + {no_response_deadline_days} days):{RESET}")
        for u in updated:
            print(f"    ✗ {u}")

    # ── Instructions for manual reply update ─────────────────────
    print(f"\n  {BOLD}To mark a reply received:{RESET}")
    print(f"  Edit jobs.csv → change status to 'replied' for the matching job")
    print(f"  Or run: {CYAN}python orchestrator.py --mark-replied <job_id>{RESET}\n")


def mark_replied(job_id: str):
    """Manually mark a job as replied."""
    jobs = load_jobs()
    found = False
    for job in jobs:
        if job["id"] == job_id:
            job["status"] = "replied"
            job["replied_at"] = now().isoformat()
            found = True
            print(f"{GREEN}✓ Marked {job['company']} / {job['role']} as replied{RESET}")
            break
    if not found:
        print(f"{RED}Job ID '{job_id}' not found in jobs.csv{RESET}")
        return
    save_jobs(jobs)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def _status_color(status: str) -> str:
    return {
        "pending":     DIM,
        "sent":        CYAN,
        "followed_up": YELLOW,
        "replied":     GREEN,
        "no_response": RED,
        "bounced":     RED,
        "rejected":    RED,
    }.get(status, RESET)


def _phase_color(phase: str) -> str:
    return {
        "SENDING":    CYAN,
        "FOLLOW_UP":  YELLOW,
        "COLLECTING": DIM,
        "EVALUATING": GREEN,
    }.get(phase, RESET)


def _fmt_dt(iso: str) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%b %d %H:%M UTC")
    except Exception:
        return iso


def _days_ago(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        delta = now() - dt
        if delta.days == 0:
            return "(today)"
        return f"({delta.days}d ago)"
    except Exception:
        return ""


def print_section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")
    print("─" * 60)


def main_dashboard():
    config  = load_json("config.json")
    state   = load_json("state.json")
    variant = load_json("variants.json")
    jobs    = load_jobs()
    results = load_results()

    print(f"\n{BOLD}{'=' * 60}")
    print("  JOB APPLICATION AGENT — DASHBOARD")
    print(f"{'=' * 60}{RESET}")
    print(f"  {DIM}As of {now().strftime('%Y-%m-%d %H:%M UTC')}{RESET}")

    # ── Phase & Variant ──────────────────────────────────────────
    print_section("CURRENT STATUS")
    phase = state.get("phase", "—")
    phase_col = _phase_color(phase)
    print(f"  Phase      : {phase_col}{BOLD}{phase}{RESET}")
    print(f"  Variant    : {variant.get('id', '—')}  —  {DIM}{variant.get('description', '')}{RESET}")
    print(f"  Applicant  : {config.get('applicant_name', '—')}")
    print(f"  Batch size : {config.get('batch_size', '—')}")
    if state.get("batch_sent_at"):
        print(f"  Batch sent : {_fmt_dt(state['batch_sent_at'])} {_days_ago(state['batch_sent_at'])}")

    # ── Applications ─────────────────────────────────────────────
    print_section("APPLICATIONS")
    if not jobs:
        print(f"  {DIM}No jobs in jobs.csv yet.{RESET}")
    else:
        status_counts = {}
        for job in jobs:
            s = job.get("status", "pending")
            status_counts[s] = status_counts.get(s, 0) + 1

        total = len(jobs)
        summary_parts = []
        for s in ["pending", "sent", "followed_up", "replied", "no_response", "bounced"]:
            if status_counts.get(s):
                col = _status_color(s)
                summary_parts.append(f"{col}{status_counts[s]} {s}{RESET}")
        print(f"  Total: {total}  |  " + "  ".join(summary_parts))
        print()

        col_widths = {"company": 18, "role": 22, "status": 12, "sent_at": 17}
        header = (
            f"  {'Company':<{col_widths['company']}}"
            f"{'Role':<{col_widths['role']}}"
            f"{'Status':<{col_widths['status']}}"
            f"Sent"
        )
        print(f"{DIM}{header}{RESET}")
        print(f"  {DIM}{'─' * 72}{RESET}")

        for job in jobs:
            status = job.get("status", "pending")
            col = _status_color(status)
            company = job["company"][:col_widths["company"] - 1].ljust(col_widths["company"])
            role    = job["role"][:col_widths["role"] - 1].ljust(col_widths["role"])
            st      = status.ljust(col_widths["status"])
            sent    = _fmt_dt(job.get("sent_at", ""))
            print(f"  {company}{role}{col}{st}{RESET}{DIM}{sent}{RESET}")

    # ── Follow-ups Due ───────────────────────────────────────────
    due_today = [
        j for j in jobs
        if j.get("status") == "sent"
        and j.get("follow_up_at")
        and datetime.fromisoformat(j["follow_up_at"].replace("Z", "+00:00")) <= now()
    ]
    if due_today:
        print_section(f"FOLLOW-UPS DUE  ({len(due_today)})")
        for job in due_today:
            print(f"  {YELLOW}→ {job['company']} / {job['role']}  ({job['contact_email']}){RESET}")

    # ── Replies received ─────────────────────────────────────────
    replied = [j for j in jobs if j.get("status") == "replied"]
    if replied:
        print_section(f"REPLIES RECEIVED  ({len(replied)})")
        for job in replied:
            print(f"  {GREEN}★ {job['company']} / {job['role']}  ({_fmt_dt(job.get('replied_at', ''))}){RESET}")

    # ── No response ───────────────────────────────────────────────
    no_resp = [j for j in jobs if j.get("status") == "no_response"]
    if no_resp:
        print_section(f"NO RESPONSE  ({len(no_resp)})")
        for job in no_resp:
            print(f"  {RED}✗ {job['company']} / {job['role']}{RESET}")

    # ── Variant Performance ──────────────────────────────────────
    print_section("VARIANT PERFORMANCE (results.tsv)")
    if not results:
        print(f"  {DIM}No completed experiments yet.{RESET}")
    else:
        print(f"  {'ID':<6} {'Rate':>7}  {'Sent':>5}  {'Replies':>7}  {'Status':<8}  Description")
        print(f"  {DIM}{'─' * 70}{RESET}")
        for r in results:
            rate = float(r["reply_rate"])
            col = GREEN if rate >= 0.15 else (YELLOW if rate >= 0.05 else RED)
            status_col = GREEN if r["status"] == "keep" else RED
            print(
                f"  {r['variant_id']:<6} "
                f"{col}{rate:>6.1%}{RESET}  "
                f"{r['applications_sent']:>5}  "
                f"{r['replies']:>7}  "
                f"{status_col}{r['status']:<8}{RESET}  "
                f"{DIM}{r['description']}{RESET}"
            )

    # ── Next Action ──────────────────────────────────────────────
    print_section("NEXT ACTION")
    if phase == "SENDING":
        pending_count = len([j for j in jobs if j["status"] == "pending"])
        print(f"  Run {CYAN}python engine.py{RESET} to send up to {config.get('batch_size', 20)} applications.")
        print(f"  ({pending_count} pending jobs in queue)")
    elif phase == "FOLLOW_UP":
        print(f"  Run {CYAN}python engine.py{RESET} to send follow-up emails when due.")
        if due_today:
            print(f"  {YELLOW}{len(due_today)} follow-up(s) ready to send now.{RESET}")
    elif phase == "COLLECTING":
        if state.get("batch_sent_at"):
            eval_days = config.get("eval_window_days", 5)
            deadline = datetime.fromisoformat(state["batch_sent_at"].replace("Z", "+00:00")) + timedelta(days=eval_days)
            remaining = deadline - now()
            if remaining.total_seconds() > 0:
                print(f"  Waiting for eval window. Closes in {remaining.days}d {remaining.seconds // 3600}h.")
                print(f"  Run {CYAN}python orchestrator.py --check{RESET} daily to check for replies.")
            else:
                print(f"  Eval window elapsed. Run {CYAN}python engine.py{RESET} to evaluate.")
    elif phase == "EVALUATING":
        print(f"  Run {CYAN}python engine.py{RESET} to evaluate results and generate next variant.")

    print(f"\n{'─' * 60}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--check" in args:
        check_replies_and_update()
        main_dashboard()
    elif "--mark-replied" in args:
        idx = args.index("--mark-replied")
        if idx + 1 < len(args):
            mark_replied(args[idx + 1])
        else:
            print(f"{RED}Usage: python orchestrator.py --mark-replied <job_id>{RESET}")
    else:
        main_dashboard()
