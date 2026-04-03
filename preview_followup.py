"""
preview_followup.py — Preview consolidated follow-up emails without sending.

Usage:
    python3 preview_followup.py
"""

import json
import os
from dotenv import load_dotenv
load_dotenv()

import cover_letter

# Snaphunt — multiple roles, same email
snaphunt_jobs = [
    {"company": "Snaphunt Pte Ltd", "role": "Technical Product Manager", "contact_email": "apply@snaphunt.com"},
    {"company": "Snaphunt Pte Ltd", "role": "Junior Product Manager", "contact_email": "apply@snaphunt.com"},
    {"company": "Snaphunt Pte Ltd", "role": "Youtube Product Manager AI", "contact_email": "apply@snaphunt.com"},
    {"company": "Snaphunt Pte Ltd", "role": "Compliance Product Manager – Crypto", "contact_email": "apply@snaphunt.com"},
    {"company": "Snaphunt Pte Ltd", "role": "Risk Product Manager – Crypto", "contact_email": "apply@snaphunt.com"},
    {"company": "Snaphunt Pte Ltd", "role": "Product Analyst: IMOS Platform", "contact_email": "apply@snaphunt.com"},
]

# Horizon Labs — single role
horizon_jobs = [
    {"company": "Horizon Labs", "role": "Product Analyst Intern", "contact_email": "hr@horizonlabs.ai"},
]

APPLICANT = "Harshkumar Patel"

def preview(label, jobs):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    result = cover_letter.generate_consolidated_follow_up(jobs=jobs, applicant_name=APPLICANT)
    print(f"SUBJECT: {result['subject']}")
    print("-" * 60)
    print(result["cover_letter"])

preview("SNAPHUNT — 6 roles, 1 email", snaphunt_jobs)
preview("HORIZON LABS — 1 role, 1 email", horizon_jobs)
