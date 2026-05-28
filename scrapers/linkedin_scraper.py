"""
linkedin_scraper.py — Scrape LinkedIn jobs via Apify and match against resume

Usage:
    python3 linkedin_scraper.py

Searches LinkedIn for roles aligned with your resume, scores each with OpenAI,
and saves qualifying jobs (score >= MATCH_THRESHOLD) to jobs.csv + job_descriptions/.
"""

import csv
import json
import os
import re
import urllib.parse
import urllib.request

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS_CSV = os.path.join(BASE_DIR, "jobs.csv")
JD_DIR = os.path.join(BASE_DIR, "job_descriptions")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# ── Tune these ─────────────────────────────────────────────────────────────────
SEARCH_URLS = [
    "https://www.linkedin.com/jobs/search/?keywords=product+manager&location=Singapore",
    "https://www.linkedin.com/jobs/search/?keywords=product+analyst&location=Singapore",
    "https://www.linkedin.com/jobs/search/?keywords=business+analyst&location=Singapore",
    "https://www.linkedin.com/jobs/search/?keywords=strategy+analyst&location=Singapore",
    "https://www.linkedin.com/jobs/search/?keywords=growth+manager&location=Singapore",
]
MAX_ITEMS_PER_QUERY = 30   # cap applied after fetching (actor returns full pages)
MATCH_THRESHOLD = 6        # min score (out of 10) to save

# Paste your resume summary here — used by OpenAI to score job fit.
# Be specific: include current role, past roles with metrics, education, skills, and target roles.
RESUME_TEXT = """
Your Name — brief professional tagline.
Currently: [Role] at [Company], [City] ([Month Year]–present).
  - Key achievement 1
  - Key achievement 2

Prior: [Role] at [Company], [Role] at [Company].

Education: [Degree] from [University].

Skills: skill1, skill2, skill3 ...

Target: [Role 1], [Role 2] — [City].
"""


def run():
    try:
        from apify_client import ApifyClient
    except ImportError:
        raise RuntimeError("Run: pip install apify-client")

    apify_token = os.environ.get("APIFY_API_KEY") or os.environ.get("APIFY_API_TOKEN")
    if not apify_token:
        raise RuntimeError("APIFY_API_KEY not found in .env")

    openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    apify_client = ApifyClient(apify_token)
    hunter_key = os.environ.get("hunter_api_key") or os.environ.get("HUNTER_API_KEY") or ""
    if not hunter_key:
        print("[warning] HUNTER_API_KEY not found — emails will be blank")
    _domain_cache: dict[str, str] = {}  # company domain → best HR email found

    # ── Step 1: Fetch jobs from LinkedIn via Apify ─────────────────────────────
    raw_jobs: list[dict] = []
    seen_urls: set[str] = set()

    for search_url in SEARCH_URLS:
        keyword = search_url.split("keywords=")[1].split("&")[0].replace("+", " ")
        print(f"\n[apify] Searching: {keyword!r} in Singapore ...")
        try:
            run_result = apify_client.actor("curious_coder/linkedin-jobs-scraper").call(
                run_input={
                    "urls": [search_url],
                    "proxy": {"useApifyProxy": True},
                }
            )
            dataset_id = run_result.get("defaultDatasetId")
            items = list(apify_client.dataset(dataset_id).iterate_items())
            count = 0
            for item in items[:MAX_ITEMS_PER_QUERY]:
                url = item.get("link") or item.get("url") or ""
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    raw_jobs.append(item)
                    count += 1
            print(f"  → {count} added (deduped total: {len(raw_jobs)})")
        except Exception as e:
            print(f"  [error] {e}")

    if not raw_jobs:
        print("\n[scraper] No jobs returned from Apify. Check actor name / token.")
        return

    print(f"\n[scraper] Scoring {len(raw_jobs)} jobs against resume ...")

    # ── Step 2: Score each job against resume ─────────────────────────────────
    matched: list[dict] = []

    for i, item in enumerate(raw_jobs, 1):
        title = (item.get("title") or item.get("jobTitle") or "").strip()
        company = (item.get("companyName") or item.get("company") or "Unknown").strip()
        description = (item.get("descriptionText") or item.get("descriptionHtml") or "").strip()
        url = item.get("link") or item.get("url") or ""
        location = (item.get("location") or "Singapore").strip()

        if not title or not description:
            continue

        print(f"  [{i}/{len(raw_jobs)}] Scoring: {title} @ {company} ...", end=" ", flush=True)

        score, reason = _score_job(openai_client, title, company, description)
        print(f"score={score}/10")

        if score >= MATCH_THRESHOLD:
            # Extract company domain for Hunter lookup
            website = (item.get("companyWebsite") or "").strip()
            domain = _extract_domain(website) if website else ""

            matched.append({
                "title": title,
                "company": company,
                "description": description,
                "url": url,
                "location": location,
                "score": score,
                "reason": reason,
                "domain": domain,
            })

    print(f"\n[scraper] {len(matched)}/{len(raw_jobs)} jobs matched (score >= {MATCH_THRESHOLD})")

    if not matched:
        print("  No jobs met the threshold. Try lowering MATCH_THRESHOLD.")
        return

    # ── Step 2.5: Find HR/recruiter emails via Hunter.io ──────────────────────
    if hunter_key:
        print(f"\n[hunter] Looking up recruiter emails for {len(matched)} companies ...")
        for job in matched:
            domain = job.get("domain", "")
            company = job["company"]
            if domain in _domain_cache:
                job["contact_email"] = _domain_cache[domain]
                print(f"  [cache] {company} → {job['contact_email'] or '(none)'}")
                continue
            email = _find_hr_email(hunter_key, domain, company)
            _domain_cache[domain] = email
            job["contact_email"] = email
            status = email or "(not found)"
            print(f"  {company} → {status}")
    else:
        for job in matched:
            job["contact_email"] = ""

    # ── Step 3: Save to jobs.csv + job_descriptions/ ──────────────────────────
    os.makedirs(JD_DIR, exist_ok=True)
    existing = _load_existing_jobs()
    existing_urls = {j.get("url", "") for j in existing}
    next_id = _next_job_id(existing)

    new_jobs = []
    for job in matched:
        if job["url"] in existing_urls:
            print(f"[scraper] Skipping duplicate: {job['title']} @ {job['company']}")
            continue

        job_id = f"job_{next_id:03d}"
        jd_file = f"{job_id}.txt"
        jd_path = os.path.join(JD_DIR, jd_file)

        with open(jd_path, "w", encoding="utf-8") as f:
            f.write(f"Company: {job['company']}\n")
            f.write(f"Role: {job['title']}\n")
            f.write(f"Location: {job['location']}\n")
            f.write(f"Source: {job['url']}\n")
            f.write(f"Match Score: {job['score']}/10 — {job['reason']}\n\n")
            f.write(job["description"])

        new_jobs.append({
            "id": job_id,
            "company": job["company"],
            "role": job["title"],
            "contact_email": job.get("contact_email", ""),
            "job_description_file": jd_file,
            "variant_id": "",
            "status": "pending",
            "sent_at": "",
            "follow_up_at": "",
            "follow_up_sent_at": "",
            "replied_at": "",
            "message_id": "",
            "url": job["url"],
            "match_score": job["score"],
        })

        existing_urls.add(job["url"])
        next_id += 1

    fieldnames = [
        "id", "company", "role", "contact_email", "job_description_file",
        "variant_id", "status", "sent_at", "follow_up_at",
        "follow_up_sent_at", "replied_at", "message_id", "url", "match_score",
    ]

    all_jobs = []
    for j in existing:
        row = {k: j.get(k, "") for k in fieldnames}
        all_jobs.append(row)
    all_jobs.extend(new_jobs)

    with open(JOBS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_jobs)

    print(f"\n[scraper] Done! Added {len(new_jobs)} new jobs.")
    print(f"\n  {'Score':<6} {'Company':<28} {'Role'}")
    print(f"  {'-'*6} {'-'*28} {'-'*40}")
    for j in new_jobs:
        print(f"  {j['match_score']:<6} {j['company'][:27]:<28} {j['role'][:40]}")

    print(f"\n  Next: python3 engine.py")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _score_job(client: OpenAI, title: str, company: str, description: str) -> tuple[int, str]:
    """Score a job 1-10 against the resume. Returns (score, reason)."""
    prompt = f"""You are a job-match evaluator. Score how well the candidate's profile matches this job on a scale of 1-10.

Candidate profile:
{RESUME_TEXT}

Job title: {title}
Company: {company}
Job description (first 1500 chars):
{description[:1500]}

Scoring guide:
- 8-10: Strong match — role aligns with PM/BA/strategy experience, Singapore-based
- 6-7: Good match — relevant skills apply, minor gaps
- 4-5: Partial match — some transferable skills but significant gaps
- 1-3: Poor match — unrelated field or requires expertise candidate lacks

Reply with ONLY this JSON (no markdown):
{{"score": <int 1-10>, "reason": "<one sentence why>"}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=80,
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()
        data = json.loads(raw)
        return int(data["score"]), str(data.get("reason", ""))
    except Exception:
        return 0, "scoring error"


def _find_hr_email(api_key: str, domain: str, company: str) -> str:
    """Search Hunter.io for an HR/recruiter email at the given domain or company."""
    HR_TITLES = ["hr", "human resources", "talent", "recruiter", "people", "hiring"]

    # Try domain-search first if we have a domain
    targets = []
    if domain:
        targets.append(f"https://api.hunter.io/v2/domain-search?domain={domain}&department=human_resources&limit=10&api_key={api_key}")
    # Fallback: search by company name
    targets.append(f"https://api.hunter.io/v2/domain-search?company={urllib.parse.quote(company)}&department=human_resources&limit=10&api_key={api_key}")

    for url in targets:
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            emails = data.get("data", {}).get("emails", [])
            if not emails:
                continue
            # Prefer HR/talent/recruiter titles
            for e in emails:
                pos = (e.get("position") or "").lower()
                if any(kw in pos for kw in HR_TITLES):
                    return e["value"]
            # Fallback to first verified email
            for e in emails:
                if e.get("confidence", 0) >= 70:
                    return e["value"]
            if emails:
                return emails[0]["value"]
        except Exception:
            continue
    return ""


def _extract_domain(url: str) -> str:
    """Extract bare domain from a URL."""
    try:
        parsed = urllib.parse.urlparse(url if "://" in url else "https://" + url)
        domain = parsed.netloc or parsed.path
        return domain.lstrip("www.").split("/")[0]
    except Exception:
        return ""


def _load_existing_jobs() -> list[dict]:
    if not os.path.exists(JOBS_CSV):
        return []
    with open(JOBS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _next_job_id(existing: list[dict]) -> int:
    if not existing:
        return 1
    ids = []
    for j in existing:
        m = re.match(r"job_(\d+)", j.get("id", ""))
        if m:
            ids.append(int(m.group(1)))
    return max(ids) + 1 if ids else len(existing) + 1


if __name__ == "__main__":
    run()
