"""
preview_followup.py — Preview consolidated follow-up emails without sending.

Usage:
    python3 utils/preview_followup.py
"""

import json
import os
import sys
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import cover_letter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(BASE_DIR, "config.json")) as f:
    config = json.load(f)

APPLICANT = config["applicant_name"]
CONTACT_LINE = config.get("contact_line", "")

# Example: multiple roles at the same company (consolidated into one email)
multi_role_jobs = [
    {"company": "Acme Corp", "role": "Product Manager", "contact_email": "hr@acme.com"},
    {"company": "Acme Corp", "role": "Product Analyst", "contact_email": "hr@acme.com"},
    {"company": "Acme Corp", "role": "Growth Manager", "contact_email": "hr@acme.com"},
]

# Example: single role
single_role_jobs = [
    {"company": "Beta Startup", "role": "Business Analyst Intern", "contact_email": "careers@beta.com"},
]


def preview(label, jobs):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    result = cover_letter.generate_consolidated_follow_up(
        jobs=jobs,
        applicant_name=APPLICANT,
        contact_line=CONTACT_LINE,
    )
    print(f"SUBJECT: {result['subject']}")
    print("-" * 60)
    print(result["cover_letter"])


preview("MULTI-ROLE — 3 roles, 1 email", multi_role_jobs)
preview("SINGLE-ROLE — 1 role, 1 email", single_role_jobs)
