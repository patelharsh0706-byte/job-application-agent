"""
score_and_enrich.py — Score first 25 scraped jobs and find HR emails

Usage:
    python3 score_and_enrich.py
"""

import csv
import json
import os
import urllib.parse
import urllib.request
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_CSV = os.path.join(BASE_DIR, "scraped_jobs.csv")
OUTPUT_CSV = os.path.join(BASE_DIR, "matched_jobs.csv")

MATCH_THRESHOLD = 6
BATCH_SIZE = 25

RESUME_TEXT = """
Harshkumar Patel — engineer-turned-PM, MSc Management of Technology & Innovation (NUS Singapore, 2025-2026).
Currently: Product Management Intern at Purands, Singapore (Feb 2026–present).
  - End-to-end product roadmap, market & competitor analysis, OKRs/KPIs, feature prioritisation
  - Feature testing, UX gap identification, developer briefs
  - Vibecoded and shipped full production website (purands.com) end-to-end using AI-assisted dev tools
  - Built AI-powered sales outreach system: automated prospect discovery + personalised cold outreach at scale
  - Developed AI Email Optimizer: LLM-driven personalisation of email content per recipient at scale
  - AI-assisted prototyping (OpenAI Codex, Claude), UI/UX redesign using design thinking

Prior: Business Analyst simulation (Talent Geist), Team Lead R&D/Tech Entrepreneurship (NUS — 20+ customer
       discovery interviews, 3-year GTM roadmap, startup P&L modelling),
       Mechanical Maintenance Engineer 3 yrs (Reliance Industries — $850K cost savings, SAP PM/MM),
       Business Development & Marketing Intern (Stackby — B2B growth, 3 new client acquisitions).

Education: MSc MOTI NUS (modules: Marketing of Tech Products, IP Management & Innovation Strategy,
           Venture Capital Funding, Tech Entrepreneurial Strategy, Tech Launch);
           BTech Mechanical Engineering NIT Surat.

Skills: Product roadmapping, backlog management, OKRs/KPIs, GTM strategy, customer discovery,
A/B testing, product-market fit, agile (scrum/kanban), design thinking, prototype-driven development,
market research, competitive analysis, business case development, unit economics, stakeholder management,
strategic planning, data-driven decision making, Python (basic), SQL (basic), Figma, UI/UX,
Prompt Engineering, LLM application building, Google Analytics, Facebook & Instagram Ads, Canva.

Target: Product Manager, Product Analyst, Business Analyst, Strategy Analyst, Growth Manager — Singapore.
"""


def run():
    openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    hunter_key = os.environ.get("hunter_api_key") or os.environ.get("HUNTER_API_KEY") or ""

    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        jobs = list(csv.DictReader(f))[:BATCH_SIZE]

    print(f"Processing first {len(jobs)} jobs...\n")

    results = []
    domain_cache = {}

    for i, job in enumerate(jobs, 1):
        title = job.get("title", "")
        company = job.get("company", "")
        description = job.get("description_preview", "")
        linkedin_url = job.get("linkedin_url", "")
        apply_url = job.get("apply_url", "")
        website = job.get("company_website", "")

        print(f"[{i:02d}/25] {title} @ {company}")

        # Score
        score, reason = _score_job(openai_client, title, company, description)
        print(f"       Score: {score}/10 — {reason}")

        # Email via Hunter
        email = ""
        if hunter_key and score >= MATCH_THRESHOLD:
            domain = _extract_domain(website) if website else ""
            cache_key = domain or company
            if cache_key in domain_cache:
                email = domain_cache[cache_key]
                print(f"       Email: {email or '(cached: none)'}")
            else:
                email = _find_hr_email(hunter_key, domain, company)
                domain_cache[cache_key] = email
                print(f"       Email: {email or '(not found)'}")
        elif score < MATCH_THRESHOLD:
            print(f"       → Below threshold, skipping email lookup")

        results.append({
            "rank": i,
            "score": score,
            "title": title,
            "company": company,
            "location": job.get("location", ""),
            "seniority": job.get("seniority", ""),
            "employment_type": job.get("employment_type", ""),
            "easy_apply": job.get("easy_apply", ""),
            "contact_email": email,
            "apply_url": apply_url,
            "linkedin_url": linkedin_url,
            "match_reason": reason,
        })
        print()

    # Sort by score desc
    results.sort(key=lambda x: x["score"], reverse=True)

    fieldnames = ["rank", "score", "title", "company", "location", "seniority",
                  "employment_type", "easy_apply", "contact_email", "apply_url",
                  "linkedin_url", "match_reason"]

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    # Report
    matched = [r for r in results if r["score"] >= MATCH_THRESHOLD]
    print("\n" + "="*70)
    print(f"RESULTS: {len(matched)}/{len(results)} jobs scored >= {MATCH_THRESHOLD}/10")
    print("="*70)
    print(f"{'#':<4} {'Score':<7} {'Company':<25} {'Role':<30} {'Email'}")
    print(f"{'-'*4} {'-'*7} {'-'*25} {'-'*30} {'-'*25}")
    for r in results:
        marker = "✓" if r["score"] >= MATCH_THRESHOLD else " "
        email_str = r["contact_email"] or "(no email)"
        print(f"{marker}{r['rank']:<3} {r['score']:<7} {r['company'][:24]:<25} {r['title'][:29]:<30} {email_str}")

    print(f"\nSaved to: matched_jobs.csv")


def _score_job(client, title, company, description):
    prompt = f"""Score how well this candidate matches the job (1-10).

Candidate:
{RESUME_TEXT}

Job: {title} at {company}
Description: {description[:1200]}

Scoring:
8-10: Strong match (PM/BA/strategy, Singapore)
6-7: Good match, minor gaps
4-5: Partial match
1-3: Poor match

Reply ONLY with JSON: {{"score": <int>, "reason": "<one sentence>"}}"""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=80, temperature=0,
        )
        data = json.loads(resp.choices[0].message.content.strip())
        return int(data["score"]), str(data.get("reason", ""))
    except Exception:
        return 0, "scoring error"


def _find_hr_email(api_key, domain, company):
    HR_KEYWORDS = ["hr", "human resources", "talent", "recruiter", "people", "hiring"]
    targets = []
    if domain:
        targets.append(f"https://api.hunter.io/v2/domain-search?domain={domain}&department=human_resources&limit=10&api_key={api_key}")
    targets.append(f"https://api.hunter.io/v2/domain-search?company={urllib.parse.quote(company)}&department=human_resources&limit=10&api_key={api_key}")
    for url in targets:
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            emails = data.get("data", {}).get("emails", [])
            if not emails:
                continue
            for e in emails:
                if any(kw in (e.get("position") or "").lower() for kw in HR_KEYWORDS):
                    return e["value"]
            for e in emails:
                if e.get("confidence", 0) >= 70:
                    return e["value"]
            if emails:
                return emails[0]["value"]
        except Exception:
            continue
    return ""


def _extract_domain(url):
    try:
        parsed = urllib.parse.urlparse(url if "://" in url else "https://" + url)
        return (parsed.netloc or parsed.path).lstrip("www.").split("/")[0]
    except Exception:
        return ""


if __name__ == "__main__":
    run()
