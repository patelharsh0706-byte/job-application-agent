"""
engine.py — Fixed, read-only. Do not modify.

The hourly state machine. Reads state.json, executes the appropriate phase,
writes updated state.json back. Called by GitHub Actions every hour.

Usage: python engine.py

Configuration (edit these at the top — they are the only knobs):
"""

import csv
import json
import os
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
import orchestrator as orc

# ---------------------------------------------------------------------------
# Configuration — edit these
# ---------------------------------------------------------------------------

BATCH_SIZE = 50                  # emails sent per variant (min for statistical signal)
EVAL_WINDOW_HOURS = 48           # hours to wait before judging a variant
MIN_REPLIES_FOR_EARLY_STOP = 10  # stop collecting early if this many replies received

# ---------------------------------------------------------------------------
# Paths (relative to this file)
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "state.json"
VARIANTS_FILE = BASE_DIR / "variants.json"
RESULTS_FILE = BASE_DIR / "results.tsv"
PROSPECTS_FILE = BASE_DIR / "prospects.csv"

# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

PHASE_SENDING = "SENDING"
PHASE_COLLECTING = "COLLECTING"
PHASE_EVALUATING = "EVALUATING"


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return _initial_state()


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _initial_state() -> dict:
    variant = json.loads(VARIANTS_FILE.read_text())
    return {
        "phase": PHASE_SENDING,
        "variant_id": variant["variant_id"],
        "batch_start_index": 0,
        "emails_sent": 0,
        "replies": 0,
        "sending_started_at": None,
        "collecting_started_at": None,
        "sent_emails": [],
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run():
    state = load_state()
    phase = state["phase"]
    print(f"[engine] Phase: {phase} | Variant: {state.get('variant_id')} | "
          f"Sent: {state.get('emails_sent', 0)} | Replies: {state.get('replies', 0)}")

    orc.agent_start("state_machine")
    try:
        if phase == PHASE_SENDING:
            state = phase_sending(state)
        elif phase == PHASE_COLLECTING:
            state = phase_collecting(state)
        elif phase == PHASE_EVALUATING:
            state = phase_evaluating(state)
        else:
            print(f"[engine] Unknown phase '{phase}', resetting to SENDING")
            state = _initial_state()
        orc.agent_success("state_machine", f"phase={phase} variant={state.get('variant_id')}")
    except Exception as e:
        orc.agent_error("state_machine", str(e))
        raise

    save_state(state)
    print("[engine] Done.")


# ---------------------------------------------------------------------------
# Phase: SENDING
# ---------------------------------------------------------------------------

def phase_sending(state: dict) -> dict:
    from core.email_client import send_email, render_template

    prospects = load_prospects()
    variant = json.loads(VARIANTS_FILE.read_text())
    sender_vars = {
        "sender_name": os.environ.get("SENDER_NAME", ""),
        "sender_title": os.environ.get("SENDER_TITLE", ""),
        "sender_company": os.environ.get("SENDER_COMPANY", ""),
    }

    start_idx = state.get("batch_start_index", 0)
    already_sent = {e["to_email"] for e in state.get("sent_emails", [])}

    # Find prospects not yet emailed in this batch
    remaining = [p for p in prospects[start_idx:] if p["email"] not in already_sent]
    to_send = remaining[:BATCH_SIZE - state.get("emails_sent", 0)]

    if not to_send:
        print("[engine] All batch emails sent. Transitioning to COLLECTING.")
        state["phase"] = PHASE_COLLECTING
        state["collecting_started_at"] = _now_iso()
        return state

    if state.get("sending_started_at") is None:
        state["sending_started_at"] = _now_iso()

    sent_count = 0
    for prospect in to_send:
        variables = {**sender_vars, **prospect}
        subject = render_template(variant["subject"], variables)
        body = render_template(variant["body"], variables)

        result = send_email(prospect["email"], subject, body)

        if result["success"]:
            state["sent_emails"].append({
                "to_email": prospect["email"],
                "message_id": result.get("message_id", ""),
                "sent_at": _now_iso(),
            })
            sent_count += 1
            state["emails_sent"] = state.get("emails_sent", 0) + 1
            print(f"  [send] OK → {prospect['email']}")
            orc.agent_success("email_sender", f"sent to {prospect['email']}")
        else:
            orc.agent_error("email_sender", f"{prospect['email']}: {result.get('error')}")
            print(f"  [send] FAIL → {prospect['email']}: {result.get('error')}")

    print(f"[engine] Sent {sent_count} emails this run. Total: {state['emails_sent']}/{BATCH_SIZE}")

    if state["emails_sent"] >= BATCH_SIZE:
        print("[engine] Batch complete. Transitioning to COLLECTING.")
        state["phase"] = PHASE_COLLECTING
        state["collecting_started_at"] = _now_iso()

    return state


# ---------------------------------------------------------------------------
# Phase: COLLECTING
# ---------------------------------------------------------------------------

def phase_collecting(state: dict) -> dict:
    from core.email_client import check_replies

    # Check for new replies
    since = state.get("sending_started_at", state.get("collecting_started_at", _now_iso()))
    orc.agent_start("reply_tracker")
    try:
        replies = check_replies(state.get("sent_emails", []), since)
        state["replies"] = len(replies)
        if replies:
            print(f"[engine] {len(replies)} replies detected so far.")
        orc.agent_success("reply_tracker", f"{len(replies)} replies found")
    except Exception as e:
        orc.agent_error("reply_tracker", str(e))
        print(f"[engine] Reply check error (non-fatal): {e}")

    # Early stop: if we have enough replies, no need to wait
    if state["replies"] >= MIN_REPLIES_FOR_EARLY_STOP:
        print(f"[engine] Early stop: {state['replies']} replies >= {MIN_REPLIES_FOR_EARLY_STOP}. Evaluating now.")
        state["phase"] = PHASE_EVALUATING
        return state

    # Check if evaluation window has elapsed
    collecting_started = datetime.fromisoformat(state["collecting_started_at"].replace("Z", "+00:00"))
    elapsed_hours = (_now_dt() - collecting_started).total_seconds() / 3600
    print(f"[engine] Collecting: {elapsed_hours:.1f}h / {EVAL_WINDOW_HOURS}h elapsed.")

    if elapsed_hours >= EVAL_WINDOW_HOURS:
        print("[engine] Evaluation window closed. Transitioning to EVALUATING.")
        state["phase"] = PHASE_EVALUATING

    return state


# ---------------------------------------------------------------------------
# Phase: EVALUATING
# ---------------------------------------------------------------------------

def phase_evaluating(state: dict) -> dict:
    from core.email_client import check_replies
    from core.generate_variant import generate_next_variant

    # Final reply check
    since = state.get("sending_started_at", state.get("collecting_started_at", _now_iso()))
    orc.agent_start("reply_tracker")
    try:
        replies = check_replies(state.get("sent_emails", []), since)
        state["replies"] = len(replies)
        orc.agent_success("reply_tracker", f"final check: {len(replies)} replies")
    except Exception as e:
        orc.agent_error("reply_tracker", str(e))
        print(f"[engine] Final reply check error (non-fatal): {e}")

    emails_sent = state.get("emails_sent", 0)
    reply_count = state.get("replies", 0)
    reply_rate = reply_count / emails_sent if emails_sent > 0 else 0.0
    variant_id = state["variant_id"]

    print(f"[engine] Results — variant {variant_id}: {reply_count}/{emails_sent} replies = {reply_rate:.1%}")

    # Determine keep/discard
    status = _evaluate_status(reply_rate, state)
    variant = json.loads(VARIANTS_FILE.read_text())
    description = variant.get("description", "")

    # Log to results.tsv
    orc.agent_start("result_evaluator")
    _append_result(variant_id, reply_rate, emails_sent, reply_count, status, description)
    orc.agent_success("result_evaluator", f"{variant_id} → {reply_rate:.1%} [{status}]")
    print(f"[engine] Logged to results.tsv: {status}")

    # Generate next variant via Claude
    print("[engine] Generating next variant via Claude API...")
    orc.agent_start("copy_generator")
    try:
        new_variant = generate_next_variant(
            str(VARIANTS_FILE),
            str(RESULTS_FILE),
            state,
        )
        VARIANTS_FILE.write_text(json.dumps(new_variant, indent=2))
        orc.agent_success("copy_generator", f"wrote {new_variant['variant_id']}: {new_variant['description']}")
        print(f"[engine] New variant: {new_variant['variant_id']} — {new_variant['description']}")
    except Exception as e:
        orc.agent_error("copy_generator", str(e))
        print(f"[engine] Variant generation failed: {e}")
        traceback.print_exc()
        print("[engine] Keeping current variant for next round.")

    # Reset state for next experiment
    new_variant_data = json.loads(VARIANTS_FILE.read_text())
    new_state = {
        "phase": PHASE_SENDING,
        "variant_id": new_variant_data["variant_id"],
        "batch_start_index": state.get("batch_start_index", 0) + emails_sent,
        "emails_sent": 0,
        "replies": 0,
        "sending_started_at": None,
        "collecting_started_at": None,
        "sent_emails": [],
    }
    return new_state


# ---------------------------------------------------------------------------
# Results logging
# ---------------------------------------------------------------------------

def _append_result(variant_id, reply_rate, emails_sent, replies, status, description):
    write_header = not RESULTS_FILE.exists()
    with open(RESULTS_FILE, "a", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        if write_header:
            writer.writerow(["variant_id", "reply_rate", "emails_sent", "replies", "status", "description"])
        writer.writerow([
            variant_id,
            f"{reply_rate:.6f}",
            emails_sent,
            replies,
            status,
            description,
        ])


def _evaluate_status(reply_rate: float, state: dict) -> str:
    """Determine keep/discard based on reply rate and history."""
    results = _read_past_results()
    if not results:
        return "keep"  # baseline always kept

    past_rates = [float(r["reply_rate"]) for r in results if r.get("status") == "keep"]
    best_so_far = max(past_rates) if past_rates else 0.0

    if reply_rate >= best_so_far:
        return "keep"
    elif reply_rate < 0.02:  # < 2% is always discard
        return "discard"
    elif reply_rate < best_so_far * 0.8:  # more than 20% worse than best
        return "discard"
    else:
        return "keep"  # marginal, keep and explore from here


def _read_past_results() -> list[dict]:
    if not RESULTS_FILE.exists():
        return []
    results = []
    with open(RESULTS_FILE, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            results.append(row)
    return results


# ---------------------------------------------------------------------------
# Prospects
# ---------------------------------------------------------------------------

def load_prospects() -> list[dict]:
    if not PROSPECTS_FILE.exists():
        raise FileNotFoundError(f"prospects.csv not found at {PROSPECTS_FILE}")
    prospects = []
    with open(PROSPECTS_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("email"):
                prospects.append(row)
    return prospects


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run()
