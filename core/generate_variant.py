"""
generate_variant.py

Called by engine.py during EVALUATING phase.
Reads all past results and asks OpenAI to generate the next cover letter style variant.
"""

import json
import os
from openai import OpenAI


def generate(current_variant: dict, results: list[dict]) -> dict:
    """
    Generate the next cover letter style variant based on past performance.

    Args:
        current_variant: the variant that just finished (from variants.json)
        results: all rows from results.tsv as list of dicts

    Returns:
        A new variant dict ready to write to variants.json
    """
    history = _format_results(results)
    next_id = _next_variant_id(results)

    prompt = f"""You are optimizing a job application cover letter strategy to maximize recruiter reply rate.

## Experiment history (all variants tried so far)
{history}

## Current (just evaluated) variant
{json.dumps(current_variant, indent=2)}

## Your task
Analyze the results and generate the NEXT cover letter style variant to test.

Rules:
- Build on what worked. If a variant had reply_rate > 0.10, keep its strongest elements.
- If all variants have reply_rate < 0.05, try something fundamentally different.
- Change ONE major thing at a time (opener, tone, length, CTA, structure) — not everything at once.
- Never repeat an approach that already failed (discard status).
- Think like a scientist: form a hypothesis about why the best variant worked, then test a specific improvement.

Output a JSON object ONLY (no markdown, no explanation outside the JSON) with these exact fields:
{{
  "id": "{next_id}",
  "description": "one-line summary of what changed and why",
  "tone": "tone description",
  "structure": "step-by-step structure",
  "opener_style": "how to open the letter",
  "length": "target length",
  "cta": "call to action text",
  "avoid": "what to avoid",
  "subject_line_style": "format for subject line"
}}
"""

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content.strip()
    new_variant = json.loads(raw)
    # Ensure the id is correct
    new_variant["id"] = next_id
    return new_variant


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_results(results: list[dict]) -> str:
    if not results:
        return "No results yet — this is the first variant."
    lines = ["variant_id | reply_rate | sent | replies | status | description"]
    lines.append("-" * 70)
    for r in results:
        lines.append(
            f"{r['variant_id']} | {float(r['reply_rate']):.1%} | "
            f"{r['applications_sent']} | {r['replies']} | "
            f"{r['status']} | {r['description']}"
        )
    return "\n".join(lines)


def _next_variant_id(results: list[dict]) -> str:
    if not results:
        return "v2"
    ids = [r["variant_id"] for r in results]
    nums = []
    for vid in ids:
        if vid.startswith("v") and vid[1:].isdigit():
            nums.append(int(vid[1:]))
    if nums:
        return f"v{max(nums) + 1}"
    return f"v{len(results) + 2}"
