"""
find_hr_emails.py — Find HR/recruiter emails for all 114 scraped companies

Strategy (per company domain):
  1. Hunter.io domain-search (department=human_resources)
  2. Fallback: scrape /contact, /about, /team pages for email regex matches
  3. Cache by domain — same company appearing multiple times reuses result

Output: hr_emails.csv  (company, domain, email, source)
"""

import csv
import json
import os
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_CSV  = os.path.join(BASE_DIR, "scraped_jobs.csv")
OUTPUT_CSV = os.path.join(BASE_DIR, "hr_emails.csv")

HUNTER_KEY = os.environ.get("hunter_api_key") or os.environ.get("HUNTER_API_KEY") or ""

HR_KEYWORDS = ["hr", "human resource", "talent", "recruit", "people", "hiring", "workforce", "hrbp"]

# Large companies where public HR emails don't exist — skip scraping, save credits
SKIP_SCRAPE = {
    "google.com", "tiktok.com", "bytedance.com", "grab.com", "grab.careers",
    "shopee.com", "careers.shopee.com", "tencent.com", "linkedin.com",
    "goldmansachs.com", "jpmorganchase.com", "hsbc.com", "bnpparibas.com",
    "bnpp.lk", "accenture.com", "ey.com", "capgemini.com", "uobgroup.com",
    "ocbc.com", "binance.com", "garena.com", "sea.com",
}


def run():
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        jobs = list(csv.DictReader(f))

    # Build unique company → domain map (preserve order)
    seen_domains: dict[str, dict] = {}  # domain → {company, website}
    for job in jobs:
        website = job.get("company_website", "").strip()
        company = job.get("company", "").strip()
        domain = _extract_domain(website) if website else ""
        key = domain or company
        if key not in seen_domains:
            seen_domains[key] = {"company": company, "domain": domain, "website": website}

    total = len(seen_domains)
    print(f"Finding HR emails for {total} unique companies...\n")

    results: dict[str, str] = {}  # domain_key → email
    sources: dict[str, str] = {}  # domain_key → source label

    for i, (key, info) in enumerate(seen_domains.items(), 1):
        company = info["company"]
        domain  = info["domain"]
        website = info["website"]

        print(f"[{i:03d}/{total}] {company[:40]}", end=" ... ", flush=True)

        email = ""
        source = ""

        # ── 1. Hunter.io ──────────────────────────────────────────────────────
        if HUNTER_KEY and domain and not _should_skip(domain):
            email, source = _hunter_lookup(domain, company)

        # ── 2. Website scrape fallback ────────────────────────────────────────
        if not email and website and not _should_skip(domain):
            email, source = _scrape_website(website, domain)

        results[key] = email
        sources[key] = source
        print(email or "(not found)" + (f" [{source}]" if source and email else ""))

        time.sleep(0.3)  # polite delay

    # ── Write output ──────────────────────────────────────────────────────────
    rows = []
    seen_written = set()
    for job in jobs:
        website = job.get("company_website", "").strip()
        company = job.get("company", "").strip()
        domain  = _extract_domain(website) if website else ""
        key     = domain or company

        if key in seen_written:
            continue
        seen_written.add(key)

        email = results.get(key, "")
        source = sources.get(key, "")
        rows.append({
            "company":    company,
            "domain":     domain,
            "email":      email,
            "source":     source,
            "linkedin_url": job.get("linkedin_url", ""),
            "apply_url":  job.get("apply_url", ""),
        })

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["company", "domain", "email", "source", "linkedin_url", "apply_url"])
        writer.writeheader()
        writer.writerows(rows)

    found = sum(1 for r in rows if r["email"])
    print(f"\n{'='*60}")
    print(f"Done. Found emails for {found}/{len(rows)} companies.")
    print(f"Saved to: hr_emails.csv")
    print(f"{'='*60}\n")

    print(f"{'Company':<35} {'Email':<40} Source")
    print(f"{'-'*35} {'-'*40} {'-'*10}")
    for r in rows:
        if r["email"]:
            print(f"{r['company'][:34]:<35} {r['email']:<40} {r['source']}")


# ── Hunter.io ─────────────────────────────────────────────────────────────────

def _hunter_lookup(domain: str, company: str) -> tuple[str, str]:
    targets = [
        f"https://api.hunter.io/v2/domain-search?domain={domain}&department=human_resources&limit=10&api_key={HUNTER_KEY}",
        f"https://api.hunter.io/v2/domain-search?company={urllib.parse.quote(company)}&department=human_resources&limit=10&api_key={HUNTER_KEY}",
    ]
    for url in targets:
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = json.loads(resp.read())
            emails = data.get("data", {}).get("emails", [])
            if not emails:
                continue
            # Prefer HR-titled emails
            for e in emails:
                pos = (e.get("position") or "").lower()
                if any(kw in pos for kw in HR_KEYWORDS):
                    return e["value"], "hunter-hr"
            # Fallback: highest confidence
            best = max(emails, key=lambda e: e.get("confidence", 0))
            if best.get("confidence", 0) >= 60:
                return best["value"], "hunter"
        except Exception:
            continue
    return "", ""


# ── Website scraper ───────────────────────────────────────────────────────────

CONTACT_PATHS = ["/contact", "/contact-us", "/about", "/about-us", "/team",
                 "/careers", "/jobs", "/hr", "/people", "/company"]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

IGNORE_EMAILS = {
    "noreply", "no-reply", "support", "info", "admin", "hello", "help",
    "privacy", "legal", "press", "media", "feedback", "example", "sentry",
    "bounce", "mailer", "notifications", "do-not-reply",
}


def _scrape_website(website: str, domain: str) -> tuple[str, str]:
    base = _base_url(website)
    if not base:
        return "", ""

    pages = [base] + [base.rstrip("/") + p for p in CONTACT_PATHS]

    for page_url in pages:
        try:
            req = urllib.request.Request(page_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            emails = EMAIL_RE.findall(html)
            emails = [e.lower() for e in emails if not any(ig in e.lower() for ig in IGNORE_EMAILS)]
            emails = [e for e in emails if domain in e or _looks_corporate(e)]

            if not emails:
                continue

            # Prefer HR-titled addresses
            for e in emails:
                local = e.split("@")[0]
                if any(kw in local for kw in HR_KEYWORDS):
                    return e, "scraped-hr"

            # Fallback: first corporate email
            return emails[0], "scraped"

        except Exception:
            continue

    return "", ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_domain(url: str) -> str:
    try:
        url = url.strip()
        if not url.startswith("http"):
            url = "https://" + url
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc or parsed.path
        return host.lstrip("www.").split("/")[0].split("?")[0].lower()
    except Exception:
        return ""


def _base_url(url: str) -> str:
    try:
        url = url.strip()
        if not url.startswith("http"):
            url = "https://" + url
        parsed = urllib.parse.urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        return ""


def _should_skip(domain: str) -> bool:
    return any(skip in domain for skip in SKIP_SCRAPE)


def _looks_corporate(email: str) -> bool:
    free_domains = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com"}
    domain = email.split("@")[-1] if "@" in email else ""
    return domain not in free_domains and "." in domain


if __name__ == "__main__":
    run()
