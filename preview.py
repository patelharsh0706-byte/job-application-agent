"""
preview.py — Preview the generated cover letter WITHOUT sending.

Usage:
    python3 preview.py job_001
"""

import json
import sys
import os
from dotenv import load_dotenv
load_dotenv()

import cover_letter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def main():
    job_id = sys.argv[1] if len(sys.argv) > 1 else "job_001"

    with open(os.path.join(BASE_DIR, "config.json")) as f:
        config = json.load(f)
    with open(os.path.join(BASE_DIR, "variants.json")) as f:
        variant = json.load(f)

    import csv
    with open(os.path.join(BASE_DIR, "jobs.csv"), newline="") as f:
        jobs = {row["id"]: row for row in csv.DictReader(f)}

    if job_id not in jobs:
        print(f"Job '{job_id}' not found in jobs.csv")
        sys.exit(1)

    job = jobs[job_id]
    resume_text = cover_letter.extract_resume_text(config["resume_path"])
    result = cover_letter.generate_cover_letter(
        variant=variant,
        job=job,
        resume_text=resume_text,
        applicant_name=config["applicant_name"],
    )

    print("=" * 60)
    print(f"SUBJECT: {result['subject']}")
    print("=" * 60)
    print(result["cover_letter"])
    print("=" * 60)

if __name__ == "__main__":
    main()
