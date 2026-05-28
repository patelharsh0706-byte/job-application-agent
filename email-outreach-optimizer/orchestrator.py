"""
orchestrator.py — Master coordinator for the Email Outreach Optimizer.

Tracks every agent, their last run, status, and output. Acts as the
single source of truth for the entire pipeline. Called by engine.py
and can also be run standalone for a full status report.

Usage:
    python orchestrator.py           # print full system status
    python orchestrator.py --reset   # reset all agent statuses
"""

import json
import csv
import argparse
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent
ORCHESTRATOR_LOG = BASE_DIR / "orchestrator_log.json"
STATE_FILE       = BASE_DIR / "state.json"
VARIANTS_FILE    = BASE_DIR / "variants.json"
RESULTS_FILE     = BASE_DIR / "results.tsv"
PROSPECTS_FILE   = BASE_DIR / "prospects.csv"

# ---------------------------------------------------------------------------
# Agent registry — every agent the system uses
# ---------------------------------------------------------------------------

AGENTS = {
    "prospect_researcher": {
        "description": "Researches prospects before emailing — firmographics, trigger events, tech stack",
        "script": "agents/prospect_researcher.py",
        "triggered_by": "manual or when new prospects added to prospects.csv",
        "outputs": "prospects.csv (enriched with notes column)",
    },
    "copy_generator": {
        "description": "Calls Claude Opus to write the next email variant based on results history",
        "script": "generate_variant.py",
        "triggered_by": "engine.py during EVALUATING phase",
        "outputs": "variants.json",
    },
    "email_sender": {
        "description": "Sends rendered email copy to prospect batch via Purands API",
        "script": "email_client.py → send_email()",
        "triggered_by": "engine.py during SENDING phase",
        "outputs": "state.json (sent_emails list updated)",
    },
    "reply_tracker": {
        "description": "Checks inbox for replies to sent emails using Purands/IMAP API",
        "script": "email_client.py → check_replies()",
        "triggered_by": "engine.py during COLLECTING and EVALUATING phases",
        "outputs": "state.json (replies count updated)",
    },
    "result_evaluator": {
        "description": "Calculates reply_rate, decides keep/discard, logs to results.tsv",
        "script": "engine.py → phase_evaluating()",
        "triggered_by": "engine.py when EVAL_WINDOW_HOURS elapsed or MIN_REPLIES hit",
        "outputs": "results.tsv (new row appended)",
    },
    "state_machine": {
        "description": "Master hourly runner — reads state, dispatches to correct phase agent",
        "script": "engine.py",
        "triggered_by": "GitHub Actions cron every hour",
        "outputs": "state.json, variants.json (committed back to repo)",
    },
}

# ---------------------------------------------------------------------------
# Log structure
# ---------------------------------------------------------------------------

def load_log() -> dict:
    if ORCHESTRATOR_LOG.exists():
        return json.loads(ORCHESTRATOR_LOG.read_text())
    return _empty_log()


def save_log(log: dict) -> None:
    ORCHESTRATOR_LOG.write_text(json.dumps(log, indent=2))


def _empty_log() -> dict:
    return {
        "created_at": _now_iso(),
        "last_updated": _now_iso(),
        "total_runs": 0,
        "agents": {name: _empty_agent_entry() for name in AGENTS},
    }


def _empty_agent_entry() -> dict:
    return {
        "status": "idle",        # idle | running | success | error | skipped
        "last_run": None,
        "last_output": None,
        "last_error": None,
        "run_count": 0,
    }


# ---------------------------------------------------------------------------
# Agent lifecycle tracking (called by engine.py)
# ---------------------------------------------------------------------------

def agent_start(agent_name: str) -> None:
    log = load_log()
    entry = log["agents"].setdefault(agent_name, _empty_agent_entry())
    entry["status"] = "running"
    entry["last_run"] = _now_iso()
    log["last_updated"] = _now_iso()
    save_log(log)


def agent_success(agent_name: str, output: str = None) -> None:
    log = load_log()
    entry = log["agents"].setdefault(agent_name, _empty_agent_entry())
    entry["status"] = "success"
    entry["last_output"] = output
    entry["last_error"] = None
    entry["run_count"] = entry.get("run_count", 0) + 1
    log["total_runs"] = log.get("total_runs", 0) + 1
    log["last_updated"] = _now_iso()
    save_log(log)


def agent_error(agent_name: str, error: str) -> None:
    log = load_log()
    entry = log["agents"].setdefault(agent_name, _empty_agent_entry())
    entry["status"] = "error"
    entry["last_error"] = error
    entry["run_count"] = entry.get("run_count", 0) + 1
    log["last_updated"] = _now_iso()
    save_log(log)


def agent_skipped(agent_name: str, reason: str = None) -> None:
    log = load_log()
    entry = log["agents"].setdefault(agent_name, _empty_agent_entry())
    entry["status"] = "skipped"
    entry["last_output"] = reason
    log["last_updated"] = _now_iso()
    save_log(log)


# ---------------------------------------------------------------------------
# Status report
# ---------------------------------------------------------------------------

def print_status() -> None:
    log = load_log()
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    variant = json.loads(VARIANTS_FILE.read_text()) if VARIANTS_FILE.exists() else {}
    results = _read_results()
    prospects = _read_prospects()

    print("=" * 65)
    print("  EMAIL OUTREACH OPTIMIZER — SYSTEM STATUS")
    print("=" * 65)

    # Pipeline state
    phase = state.get("phase", "UNKNOWN")
    variant_id = state.get("variant_id", "?")
    emails_sent = state.get("emails_sent", 0)
    replies = state.get("replies", 0)
    reply_rate = replies / emails_sent if emails_sent > 0 else 0.0

    print(f"\n  PIPELINE")
    print(f"  {'Phase':<22} {phase}")
    print(f"  {'Active Variant':<22} {variant_id} — {variant.get('description', '')}")
    print(f"  {'Emails Sent':<22} {emails_sent} / 50")
    print(f"  {'Replies':<22} {replies} ({reply_rate:.1%})")
    print(f"  {'Prospects Loaded':<22} {len(prospects)}")
    print(f"  {'Experiments Run':<22} {len(results)}")

    if state.get("collecting_started_at"):
        from datetime import timedelta
        started = datetime.fromisoformat(state["collecting_started_at"].replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - started).total_seconds() / 3600
        print(f"  {'Collecting for':<22} {elapsed:.1f}h / 48h")

    # Best result so far
    if results:
        best = max(results, key=lambda r: float(r.get("reply_rate", 0)))
        best_rate = float(best["reply_rate"])
        print(f"\n  BEST RESULT SO FAR")
        print(f"  {'Variant':<22} {best['variant_id']} ({best_rate:.1%} reply rate)")
        print(f"  {'Description':<22} {best['description']}")

    # Current variant copy
    print(f"\n  CURRENT EMAIL COPY")
    print(f"  Subject: {variant.get('subject', 'N/A')}")
    body_preview = (variant.get("body", "")[:120] + "...") if variant.get("body") else "N/A"
    print(f"  Body:    {body_preview}")

    # Agent statuses
    print(f"\n  AGENTS")
    print(f"  {'Agent':<24} {'Status':<10} {'Last Run':<22} {'Runs':<6} Last Output")
    print(f"  {'-'*24} {'-'*10} {'-'*22} {'-'*6} {'-'*20}")
    for name, meta in AGENTS.items():
        entry = log["agents"].get(name, _empty_agent_entry())
        status = entry.get("status", "idle")
        last_run = entry.get("last_run") or "never"
        if last_run != "never":
            last_run = last_run[:19].replace("T", " ")
        run_count = entry.get("run_count", 0)
        output = (entry.get("last_output") or entry.get("last_error") or "")[:35]
        status_icon = {"idle": "○", "running": "►", "success": "✓", "error": "✗", "skipped": "–"}.get(status, "?")
        print(f"  {name:<24} {status_icon} {status:<8} {last_run:<22} {run_count:<6} {output}")

    # Experiment history
    if results:
        print(f"\n  EXPERIMENT HISTORY")
        print(f"  {'Variant':<10} {'Reply Rate':<12} {'Sent':<6} {'Replies':<8} {'Status':<10} Description")
        print(f"  {'-'*10} {'-'*12} {'-'*6} {'-'*8} {'-'*10} {'-'*30}")
        for r in results:
            rate = float(r.get("reply_rate", 0))
            icon = "★" if r.get("status") == "keep" else " "
            print(f"  {r['variant_id']:<10} {rate:.1%}{icon:<10} {r['emails_sent']:<6} "
                  f"{r['replies']:<8} {r['status']:<10} {r['description'][:35]}")

    print(f"\n  Last orchestrator update: {log.get('last_updated', 'never')}")
    print("=" * 65)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_results() -> list[dict]:
    if not RESULTS_FILE.exists():
        return []
    with open(RESULTS_FILE, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _read_prospects() -> list[dict]:
    if not PROSPECTS_FILE.exists():
        return []
    with open(PROSPECTS_FILE, newline="") as f:
        return [r for r in csv.DictReader(f) if r.get("email")]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Email Outreach Optimizer — Orchestrator")
    parser.add_argument("--reset", action="store_true", help="Reset all agent statuses")
    args = parser.parse_args()

    if args.reset:
        save_log(_empty_log())
        print("Orchestrator log reset.")
    else:
        print_status()
