"""
engine.py — Run this on a schedule (e.g. daily via cron or GitHub Actions).

State machine: SENDING → FOLLOW_UP → COLLECTING → EVALUATING → SENDING ...

Each run reads state.json, executes the current phase, and writes back.
"""

import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
load_dotenv()  # loads .env locally; no-op in GitHub Actions (uses secrets instead)

import cover_letter
import email_client
import generate_variant

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    with open(os.path.join(BASE_DIR, "config.json")) as f:
        return json.load(f)


def load_variant() -> dict:
    with open(os.path.join(BASE_DIR, "variants.json")) as f:
        return json.load(f)


def load_state() -> dict:
    path = os.path.join(BASE_DIR, "state.json")
    if not os.path.exists(path):
        return {"phase": "SENDING", "batch_sent_at": None, "follow_ups_sent_at": None}
    with open(path) as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(os.path.join(BASE_DIR, "state.json"), "w") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def load_jobs() -> list[dict]:
    path = os.path.join(BASE_DIR, "jobs.csv")
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


def append_result(variant_id: str, reply_rate: float, sent: int, replies: int, status: str, description: str) -> None:
    path = os.path.join(BASE_DIR, "results.tsv")
    header = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if header:
            f.write("variant_id\treply_rate\tapplications_sent\treplies\tstatus\tdescription\n")
        f.write(f"{variant_id}\t{reply_rate:.3f}\t{sent}\t{replies}\t{status}\t{description}\n")


def load_results() -> list[dict]:
    path = os.path.join(BASE_DIR, "results.tsv")
    if not os.path.exists(path):
        return []
    results = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            results.append(row)
    return results


# ---------------------------------------------------------------------------
# Phase: SENDING
# ---------------------------------------------------------------------------

def phase_sending(config: dict, variant: dict, state: dict) -> dict:
    jobs = load_jobs()
    # NEVER retry bounced jobs — Gmail will flag account as spam
    pending = [j for j in jobs if j["status"] == "pending"]

    if not pending:
        print("[engine] No pending jobs. Add jobs to jobs.csv.")
        return state

    # Duplicate check: skip if same company+email already has a sent/followed_up/replied job
    already_sent = set()
    for j in jobs:
        if j["status"] in ("sent", "followed_up", "replied"):
            already_sent.add((j["company"].strip().lower(), j["contact_email"].strip().lower()))

    safe_pending = []
    for j in pending:
        key = (j["company"].strip().lower(), j["contact_email"].strip().lower())
        if key in already_sent:
            print(f"  ⚠ SKIPPED (duplicate): {j['company']} / {j['role']} — already sent to {j['contact_email']}")
        else:
            safe_pending.append(j)

    if not safe_pending:
        print("[engine] All pending jobs are duplicates of already-sent applications. Nothing to send.")
        return state

    batch = safe_pending[: config["batch_size"]]
    print(f"[engine] SENDING — {len(batch)} applications (variant {variant['id']})")

    resume_text = cover_letter.extract_resume_text(config["resume_path"])
    now = _now_iso()

    for job in batch:
        print(f"  → {job['company']} / {job['role']} ({job['contact_email']})")
        try:
            generated = cover_letter.generate_cover_letter(
                variant=variant,
                job=job,
                resume_text=resume_text,
                applicant_name=config["applicant_name"],
            )
            result = email_client.send_application(
                to_email=job["contact_email"],
                subject=generated["subject"],
                body=generated["cover_letter"],
                resume_path=config["resume_path"],
                applicant_name=config["applicant_name"],
            )
            if result["success"]:
                follow_up_at = (_now() + timedelta(days=config["follow_up_delay_days"])).isoformat()
                _update_job(jobs, job["id"], {
                    "variant_id": variant["id"],
                    "status": "sent",
                    "sent_at": now,
                    "follow_up_at": follow_up_at,
                    "message_id": result["message_id"] or "",
                })
                print(f"     ✓ sent (message_id={result['message_id']})")
            else:
                print(f"     ✗ failed: {result['error']}")
        except Exception as e:
            print(f"     ✗ error: {e}")

    save_jobs(jobs)

    # Transition to FOLLOW_UP
    state["phase"] = "FOLLOW_UP"
    state["batch_sent_at"] = now
    state["follow_ups_sent_at"] = None
    return state


# ---------------------------------------------------------------------------
# Phase: FOLLOW_UP
# ---------------------------------------------------------------------------

def phase_follow_up(config: dict, state: dict) -> dict:
    jobs = load_jobs()
    now = _now()
    due = [
        j for j in jobs
        if j["status"] == "sent"  # bounced jobs are excluded (status="bounced")
        and j.get("follow_up_at")
        and datetime.fromisoformat(j["follow_up_at"]) <= now
    ]

    if not due:
        print("[engine] FOLLOW_UP — no follow-ups due yet.")
        return state

    # Group by contact_email — send ONE consolidated follow-up per email address
    grouped: dict[str, list[dict]] = {}
    for job in due:
        email = job["contact_email"].strip().lower()
        grouped.setdefault(email, []).append(job)

    print(f"[engine] FOLLOW_UP — {len(due)} jobs grouped into {len(grouped)} follow-up email(s)")

    for email, email_jobs in grouped.items():
        companies = list({j["company"] for j in email_jobs})
        roles = [j["role"] for j in email_jobs]
        print(f"  → {email} ({len(email_jobs)} role(s): {', '.join(roles[:3])}{'...' if len(roles) > 3 else ''})")
        try:
            generated = cover_letter.generate_consolidated_follow_up(
                jobs=email_jobs,
                applicant_name=config["applicant_name"],
            )
            result = email_client.send_plain(
                to_email=email,
                subject=generated["subject"],
                body=generated["cover_letter"],
            )
            if result["success"]:
                now_iso = _now_iso()
                for job in email_jobs:
                    _update_job(jobs, job["id"], {
                        "status": "followed_up",
                        "follow_up_sent_at": now_iso,
                    })
                print(f"     ✓ consolidated follow-up sent ({len(email_jobs)} roles)")
            else:
                print(f"     ✗ failed: {result['error']}")
        except Exception as e:
            print(f"     ✗ error: {e}")

    save_jobs(jobs)

    # Check if all sent jobs have been followed up
    jobs = load_jobs()
    still_pending_followup = [j for j in jobs if j["status"] == "sent"]
    if not still_pending_followup:
        state["phase"] = "COLLECTING"
        state["follow_ups_sent_at"] = _now_iso()
        print("[engine] All follow-ups sent → COLLECTING")

    return state


# ---------------------------------------------------------------------------
# Phase: COLLECTING
# ---------------------------------------------------------------------------

def phase_collecting(config: dict, state: dict) -> dict:
    jobs = load_jobs()
    batch_sent_at = state.get("batch_sent_at")
    if not batch_sent_at:
        print("[engine] COLLECTING — no batch_sent_at in state, resetting to SENDING")
        state["phase"] = "SENDING"
        return state

    sent_jobs = [j for j in jobs if j["status"] in ("sent", "followed_up")]
    sent_emails = [
        {"to_email": j["contact_email"], "message_id": j["message_id"], "sent_at": j["sent_at"]}
        for j in sent_jobs
        if j.get("message_id")
    ]

    print(f"[engine] COLLECTING — checking replies for {len(sent_emails)} applications")
    print("[engine] Note: Use 'python orchestrator.py' to manually check replies via Gmail MCP")
    # Gmail MCP reply checking is done via orchestrator, not engine
    # This keeps the engine simple and lets MCP handle auth separately

    # Check if eval window has elapsed
    eval_deadline = datetime.fromisoformat(batch_sent_at) + timedelta(days=config["eval_window_days"])
    if _now() >= eval_deadline:
        print("[engine] Eval window elapsed → EVALUATING")
        state["phase"] = "EVALUATING"
    else:
        remaining = eval_deadline - _now()
        print(f"[engine] Eval window closes in {remaining.days}d {remaining.seconds // 3600}h")

    return state


# ---------------------------------------------------------------------------
# Phase: EVALUATING
# ---------------------------------------------------------------------------

def phase_evaluating(config: dict, variant: dict, state: dict) -> dict:
    jobs = load_jobs()
    batch_sent_at = state.get("batch_sent_at")

    # Final reply check
    sent_jobs = [j for j in jobs if j["variant_id"] == variant["id"] and j["status"] in ("sent", "followed_up")]
    if sent_jobs and batch_sent_at:
        sent_emails = [
            {"to_email": j["contact_email"], "message_id": j["message_id"], "sent_at": j["sent_at"]}
            for j in sent_jobs if j.get("message_id")
        ]
        replies = email_client.check_replies(sent_emails, since_timestamp=batch_sent_at)
        replied_addresses = {r["to_email"].lower() for r in replies}
        now_iso = _now_iso()
        for job in jobs:
            if job["contact_email"].lower() in replied_addresses and job["status"] != "replied":
                _update_job(jobs, job["id"], {"status": "replied", "replied_at": now_iso})
        save_jobs(jobs)

    # Calculate reply rate for this variant
    jobs = load_jobs()
    variant_jobs = [j for j in jobs if j["variant_id"] == variant["id"]]
    sent_count = len([j for j in variant_jobs if j["status"] in ("sent", "followed_up", "replied", "rejected")])
    reply_count = len([j for j in variant_jobs if j["status"] == "replied"])
    reply_rate = reply_count / sent_count if sent_count > 0 else 0.0

    print(f"[engine] EVALUATING — variant {variant['id']}: {reply_count}/{sent_count} replies ({reply_rate:.1%})")

    status = "keep" if reply_rate >= 0.05 else "discard"
    append_result(
        variant_id=variant["id"],
        reply_rate=reply_rate,
        sent=sent_count,
        replies=reply_count,
        status=status,
        description=variant["description"],
    )

    # Generate next variant
    print("[engine] Generating next variant...")
    results = load_results()
    new_variant = generate_variant.generate(current_variant=variant, results=results)

    with open(os.path.join(BASE_DIR, "variants.json"), "w") as f:
        json.dump(new_variant, f, indent=2)

    print(f"[engine] New variant → {new_variant['id']}: {new_variant['description']}")

    # Reset state
    state["phase"] = "SENDING"
    state["batch_sent_at"] = None
    state["follow_ups_sent_at"] = None
    return state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _update_job(jobs: list[dict], job_id: str, updates: dict) -> None:
    for job in jobs:
        if job["id"] == job_id:
            job.update(updates)
            return


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    config = load_config()
    variant = load_variant()
    state = load_state()

    print(f"[engine] Phase: {state['phase']} | Variant: {variant['id']}")

    if state["phase"] == "SENDING":
        state = phase_sending(config, variant, state)
    elif state["phase"] == "FOLLOW_UP":
        state = phase_follow_up(config, state)
    elif state["phase"] == "COLLECTING":
        state = phase_collecting(config, state)
    elif state["phase"] == "EVALUATING":
        state = phase_evaluating(config, variant, state)
    else:
        print(f"[engine] Unknown phase: {state['phase']}, resetting to SENDING")
        state["phase"] = "SENDING"

    save_state(state)
    print(f"[engine] Done. New phase: {state['phase']}")


if __name__ == "__main__":
    main()
