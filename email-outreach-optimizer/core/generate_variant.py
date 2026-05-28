"""
generate_variant.py — Fixed, read-only. Do not modify.

Calls Claude API to generate the next email copy variant based on
all past experiment results. This is the "research loop" brain.

Environment variables required:
    ANTHROPIC_API_KEY   — Claude API key
"""

import json
import os
import csv
from pathlib import Path


def generate_next_variant(
    current_variants_path: str,
    results_tsv_path: str,
    state: dict,
) -> dict:
    """
    Read all past results, ask Claude to generate the next variant.
    Returns a new variants dict ready to write to variants.json.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    past_results = _read_results(results_tsv_path)
    current_variant = json.loads(Path(current_variants_path).read_text())

    prompt = _build_prompt(past_results, current_variant, state)

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    new_variant = _parse_variant_response(raw, past_results)
    return new_variant


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _build_prompt(past_results: list[dict], current_variant: dict, state: dict) -> str:
    results_block = _format_results_for_prompt(past_results)
    next_id = f"v{len(past_results) + 1}"

    return f"""You are an expert cold email copywriter optimizing reply rates for a B2B outreach campaign.

## Context
[CONFIGURE] Describe your target audience and campaign context here.
Example: We are sending cold emails to [role] at [company type] in [region].

Key signals about your prospect segment:
- [Signal 1 — e.g. company size, recent funding, tech stack]
- [Signal 2 — e.g. growth indicators, hiring patterns]
- [Signal 3 — e.g. competitive landscape, pain points]

## Metric
We optimize for reply_rate = replies / emails_sent. Higher is better.
Benchmark: <5% poor, 5-10% average, 10-20% strong, >20% exceptional.

## Experiment history
{results_block}

## Current variant (just evaluated)
Subject: {current_variant.get('subject', '')}
Body:
{current_variant.get('body', '')}

## Your task
Based on the experiment history and what has worked/failed, generate the NEXT email variant to test.

Rules:
1. Change ONE major thing per experiment (subject only, opening line only, CTA only, length, etc.) unless all single-variable tests have been exhausted
2. If reply_rate is improving, iterate from the best performer — small tweaks
3. If reply_rate is stuck below 5%, try something fundamentally different
4. Simpler is better — a shorter email that performs equally is preferred
5. Never fabricate metrics or client names not mentioned above
6. The personalization variables available are: {{{{first_name}}}}, {{{{company}}}}, {{{{sender_name}}}}, {{{{sender_title}}}}, {{{{sender_company}}}}

Respond with ONLY a valid JSON object in this exact format (no markdown, no explanation):
{{
  "variant_id": "{next_id}",
  "description": "one line describing what changed vs previous",
  "subject": "email subject line here",
  "body": "full email body here with {{{{first_name}}}} etc placeholders",
  "personalization_variables": ["first_name", "company", "sender_name", "sender_title", "sender_company"],
  "notes": "brief rationale for why this change should improve reply rate"
}}"""


def _format_results_for_prompt(past_results: list[dict]) -> str:
    if not past_results:
        return "No experiments yet. This will be the first variant (baseline)."

    lines = []
    for r in past_results:
        rate_pct = float(r.get("reply_rate", 0)) * 100
        lines.append(
            f"- {r['variant_id']}: {rate_pct:.1f}% reply rate "
            f"({r.get('replies', '?')}/{r.get('emails_sent', '?')} replies) "
            f"[{r.get('status', '?')}] — {r.get('description', '')}"
        )
    return "\n".join(lines)


def _parse_variant_response(raw: str, past_results: list[dict]) -> dict:
    # Strip any accidental markdown code fences
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    variant = json.loads(raw)

    # Ensure required fields
    required = ["variant_id", "description", "subject", "body"]
    for field in required:
        if field not in variant:
            raise ValueError(f"Missing required field '{field}' in Claude response")

    return variant


# ---------------------------------------------------------------------------
# Results reader
# ---------------------------------------------------------------------------

def _read_results(results_tsv_path: str) -> list[dict]:
    path = Path(results_tsv_path)
    if not path.exists():
        return []

    results = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            results.append(row)
    return results
