"""
demo.py — Dry-run demo. No emails are actually sent.

Simulates the full optimizer loop with two variants:
  - Baseline (v1): trigger event opener, long-form, free deliverable CTA
  - Challenger (v2): ultra-short, direct pain point, binary question CTA

Usage: python demo.py
"""

import json
import time
from pathlib import Path
from datetime import datetime, timezone

BASE_DIR = Path(__file__).parent.parent

# ── ANSI colours ────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
RED    = "\033[31m"
BLUE   = "\033[34m"
WHITE  = "\033[97m"
BG_DARK = "\033[48;5;234m"

def hr(char="─", width=65, color=DIM):
    print(f"{color}{char * width}{RESET}")

def header(title, color=CYAN):
    print()
    hr("═", color=color)
    print(f"{color}{BOLD}  {title}{RESET}")
    hr("═", color=color)

def section(title):
    print(f"\n{YELLOW}{BOLD}  ▶ {title}{RESET}")
    hr("─")

def tag(label, color=GREEN):
    return f"{color}{BOLD}[{label}]{RESET}"

def pause(seconds=0.6):
    time.sleep(seconds)

# ── Variant definitions ──────────────────────────────────────────────────────

BASELINE = {
    "variant_id": "v1",
    "description": "baseline — trigger event opener, long-form, free deliverable CTA",
    "subject": "{{company}}'s recent expansion — quick question about your next vertical",
    "body": (
        "Hi {{first_name}},\n\n"
        "Noticed {{company}} recently made a notable strategic shift — that kind of move "
        "usually signals a deliberate go-to-market decision, not just a routine change.\n\n"
        "Your recent client result (65% support cost reduction) suggests you've cracked "
        "something real.\n\n"
        "I'd like to send you a short competitive positioning note — no strings — on how "
        "the space is consolidating around 2–3 players. Useful or not, it's yours in 24 hours.\n\n"
        "Worth it?\n\n"
        "Alex\nGrowth Lead | Acme Co"
    ),
    "word_count": 97,
    "hypothetical_reply_rate": 0.060,   # 6.0% — decent baseline
    "hypothetical_replies": 3,
    "hypothetical_sent": 50,
}

CHALLENGER = {
    "variant_id": "v2",
    "description": "challenger — ultra-short (3 sentences), pain-first opener, single question CTA",
    "subject": "retention without paid ads — quick question",
    "body": (
        "Hi {{first_name}},\n\n"
        "Most founders we talk to are burning CAC on re-acquisition "
        "when their biggest lever is already in their existing customer base.\n\n"
        "You've proven the model works — "
        "curious whether you're seeing the same pattern repeat with your newer clients.\n\n"
        "Open to a 10-minute swap on what's working?\n\n"
        "Alex\nGrowth Lead | Acme Co"
    ),
    "word_count": 62,
    "hypothetical_reply_rate": 0.140,   # 14.0% — strong improvement
    "hypothetical_replies": 7,
    "hypothetical_sent": 50,
}

PROSPECTS_SAMPLE = [
    {"email": "alex@acmecorp.com",      "first_name": "Alex",   "company": "Acme Corp"},
    {"email": "sarah@betastart.io",     "first_name": "Sarah",  "company": "Beta Start"},
    {"email": "hello@gammastudio.co",   "first_name": "Jamie",  "company": "Gamma Studio"},
    {"email": "founder@deltalab.com",   "first_name": "Sam",    "company": "Delta Lab"},
    {"email": "ops@epsilonhq.com",      "first_name": "Jordan", "company": "Epsilon HQ"},
]

# ── Demo runner ──────────────────────────────────────────────────────────────

def main():
    header("EMAIL OUTREACH OPTIMIZER — DRY RUN DEMO", color=CYAN)
    print(f"  {DIM}No emails will actually be sent. All metrics are simulated.{RESET}")
    print(f"  {DIM}This demo runs two variants end-to-end to show the full loop.{RESET}")
    pause(1.0)

    # ── PHASE 0: System boot ─────────────────────────────────────────────────
    section("SYSTEM BOOT — Reading state.json")
    pause(0.4)
    print(f"  {tag('state_machine', BLUE)}  Phase    : SENDING")
    print(f"  {tag('state_machine', BLUE)}  Variant  : (none yet — first run)")
    print(f"  {tag('state_machine', BLUE)}  Prospects: {len(PROSPECTS_SAMPLE)} loaded from prospects.csv")
    pause(0.8)

    # ── EXPERIMENT 1: BASELINE ────────────────────────────────────────────────
    header("EXPERIMENT 1 — BASELINE  (v1)", color=YELLOW)

    section("Phase: SENDING")
    v = BASELINE
    print(f"\n  {BOLD}Subject:{RESET}  {v['subject']}")
    print(f"  {BOLD}Words:{RESET}    {v['word_count']}")
    print(f"  {BOLD}Approach:{RESET} {v['description']}\n")
    print(f"  {DIM}── Email body preview ──────────────────────────────────{RESET}")
    for line in v["body"].split("\n")[:8]:
        print(f"  {DIM}{line}{RESET}")
    print(f"  {DIM}────────────────────────────────────────────────────────{RESET}\n")
    pause(0.5)

    print(f"  {tag('email_sender', BLUE)} Sending {v['hypothetical_sent']} emails...\n")
    for i, p in enumerate(PROSPECTS_SAMPLE):
        pause(0.25)
        print(f"    {GREEN}✓{RESET}  {p['email']:<35} {DIM}→ message_id: msg_{1000+i:04d}{RESET}")
    print(f"\n    {DIM}... +{v['hypothetical_sent'] - len(PROSPECTS_SAMPLE)} more prospects{RESET}")
    pause(0.5)
    print(f"\n  {tag('state_machine', BLUE)} All {v['hypothetical_sent']} sent. Transitioning → {CYAN}COLLECTING{RESET}")

    section("Phase: COLLECTING  (simulating 48-hour window)")
    checkpoints = [
        ("Hour  6", 0),
        ("Hour 12", 1),
        ("Hour 24", 2),
        ("Hour 36", 2),
        ("Hour 48", v["hypothetical_replies"]),
    ]
    for label, reply_count in checkpoints:
        pause(0.45)
        rate = reply_count / v["hypothetical_sent"]
        bar = "█" * reply_count + "░" * (v["hypothetical_sent"] // 10 - reply_count)
        print(f"  {tag('reply_tracker', BLUE)}  {label}  │  Replies: {reply_count:>2}  │  Rate: {rate:.1%}  │  {bar}")
    print(f"\n  {tag('state_machine', BLUE)} Window closed. Transitioning → {CYAN}EVALUATING{RESET}")

    section("Phase: EVALUATING")
    pause(0.5)
    rate_v1 = v["hypothetical_reply_rate"]
    print(f"  {tag('result_evaluator', BLUE)}  {v['variant_id']} final score:")
    print(f"    Emails sent  : {v['hypothetical_sent']}")
    print(f"    Replies      : {v['hypothetical_replies']}")
    print(f"    Reply rate   : {BOLD}{rate_v1:.1%}{RESET}  {DIM}(benchmark: >10% = strong){RESET}")
    pause(0.5)
    print(f"    Status       : {YELLOW}KEEP{RESET}  {DIM}(baseline — always kept){RESET}")
    _log_result(v, "keep")
    pause(0.5)
    print(f"\n  {tag('copy_generator', BLUE)} Calling Claude Opus to generate next variant...")
    pause(1.2)
    print(f"  {tag('copy_generator', BLUE)} {GREEN}✓{RESET}  Variant v2 generated.")
    print(f"    Hypothesis: {DIM}v1 is 97 words. Reply rates tend to improve with shorter{RESET}")
    print(f"    {DIM}emails that lead with the prospect's pain, not a research hook.{RESET}")
    print(f"    {DIM}Cutting to 62 words and opening with CAC pain instead of trigger event.{RESET}")

    # ── EXPERIMENT 2: CHALLENGER ──────────────────────────────────────────────
    header("EXPERIMENT 2 — CHALLENGER  (v2)", color=GREEN)

    section("Phase: SENDING")
    v = CHALLENGER
    print(f"\n  {BOLD}Subject:{RESET}  {v['subject']}")
    print(f"  {BOLD}Words:{RESET}    {v['word_count']}  {GREEN}↓ 36% shorter than baseline{RESET}")
    print(f"  {BOLD}Approach:{RESET} {v['description']}\n")
    print(f"  {DIM}── Email body preview ──────────────────────────────────{RESET}")
    for line in v["body"].split("\n"):
        print(f"  {DIM}{line}{RESET}")
    print(f"  {DIM}────────────────────────────────────────────────────────{RESET}\n")
    pause(0.5)

    print(f"  {tag('email_sender', BLUE)} Sending {v['hypothetical_sent']} emails...\n")
    for i, p in enumerate(PROSPECTS_SAMPLE):
        pause(0.2)
        print(f"    {GREEN}✓{RESET}  {p['email']:<35} {DIM}→ message_id: msg_{2000+i:04d}{RESET}")
    print(f"\n    {DIM}... +{v['hypothetical_sent'] - len(PROSPECTS_SAMPLE)} more prospects{RESET}")
    pause(0.5)
    print(f"\n  {tag('state_machine', BLUE)} All {v['hypothetical_sent']} sent. Transitioning → {CYAN}COLLECTING{RESET}")

    section("Phase: COLLECTING  (simulating 48-hour window)")
    checkpoints_v2 = [
        ("Hour  6", 2),
        ("Hour 12", 4),
        ("Hour 24", 6),
        ("Hour 36", 7),
        ("Hour 48", v["hypothetical_replies"]),
    ]
    for label, reply_count in checkpoints_v2:
        pause(0.4)
        rate = reply_count / v["hypothetical_sent"]
        bar = "█" * reply_count + "░" * (v["hypothetical_sent"] // 10 - reply_count)
        print(f"  {tag('reply_tracker', BLUE)}  {label}  │  Replies: {reply_count:>2}  │  Rate: {rate:.1%}  │  {bar}")
    print(f"\n  {tag('state_machine', BLUE)} Window closed. Transitioning → {CYAN}EVALUATING{RESET}")

    section("Phase: EVALUATING")
    pause(0.5)
    rate_v2 = v["hypothetical_reply_rate"]
    print(f"  {tag('result_evaluator', BLUE)}  {v['variant_id']} final score:")
    print(f"    Emails sent  : {v['hypothetical_sent']}")
    print(f"    Replies      : {v['hypothetical_replies']}")
    print(f"    Reply rate   : {BOLD}{GREEN}{rate_v2:.1%}{RESET}  {DIM}(benchmark: >10% = strong){RESET}")
    lift = (rate_v2 - rate_v1) / rate_v1 * 100
    print(f"    vs baseline  : {GREEN}+{lift:.0f}% lift{RESET} over v1")
    pause(0.5)
    print(f"    Status       : {GREEN}KEEP ★ new best{RESET}")
    _log_result(v, "keep")
    pause(0.5)
    print(f"\n  {tag('copy_generator', BLUE)} Calling Claude Opus for next hypothesis...")
    pause(1.0)
    print(f"  {tag('copy_generator', BLUE)} {GREEN}✓{RESET}  Variant v3 queued.")
    print(f"    Hypothesis: {DIM}v2 works — now test whether the subject line is the bottleneck.{RESET}")
    print(f"    {DIM}Keep body identical. A/B the subject: curiosity gap vs. direct benefit.{RESET}")

    # ── FINAL SUMMARY ─────────────────────────────────────────────────────────
    header("RESULTS SUMMARY", color=CYAN)
    pause(0.5)

    print(f"\n  {'Variant':<10} {'Reply Rate':<14} {'Sent':<7} {'Replies':<9} {'Status':<10} Description")
    hr("─")
    print(f"  {'v1':<10} {rate_v1:.1%}{'':<8} {'50':<7} {'3':<9} {'keep':<10} {BASELINE['description']}")
    print(f"  {'v2':<10} {GREEN}{rate_v2:.1%} ★{RESET}{'':<6} {'50':<7} {'7':<9} {GREEN}{'keep':<10}{RESET} {CHALLENGER['description']}")
    hr("─")
    print(f"\n  {BOLD}Best so far:{RESET} v2 — {GREEN}{rate_v2:.1%} reply rate{RESET} (+{lift:.0f}% over baseline)")
    print(f"  {BOLD}Next test:{RESET}   v3 — same body as v2, new subject line variants")
    print(f"  {BOLD}Cadence:{RESET}     Runs automatically every hour via GitHub Actions")

    print(f"\n  {DIM}Run `python orchestrator.py` at any time for a live status dashboard.{RESET}")
    print()
    hr("═", color=CYAN)
    print(f"{CYAN}{BOLD}  END OF DRY RUN{RESET}")
    hr("═", color=CYAN)
    print()


def _log_result(v, status):
    results_path = BASE_DIR / "results.tsv"
    write_header = not results_path.exists() or results_path.read_text().strip() == "variant_id\treply_rate\temails_sent\treplies\tstatus\tdescription"
    with open(results_path, "a") as f:
        if write_header and results_path.stat().st_size < 60:
            f.write("variant_id\treply_rate\temails_sent\treplies\tstatus\tdescription\n")
        f.write(f"{v['variant_id']}\t{v['hypothetical_reply_rate']:.6f}\t"
                f"{v['hypothetical_sent']}\t{v['hypothetical_replies']}\t{status}\t{v['description']}\n")


if __name__ == "__main__":
    main()
