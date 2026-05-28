"""
scraper.py — Scrape job listings from internsg.com and save to jobs.csv

Usage:
    python3 scraper.py

Searches for "product manager" and "product analyst" roles,
extracts job details, and appends to jobs.csv ready for engine.py.

Requirements:
    pip install playwright
    playwright install chromium
"""

import asyncio
import csv
import os
import re
import time
from playwright.async_api import async_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS_CSV = os.path.join(BASE_DIR, "jobs.csv")
JD_DIR = os.path.join(BASE_DIR, "job_descriptions")

SEARCH_TERMS = ["product manager", "product analyst"]
BASE_URL = "https://www.internsg.com"


async def scrape():
    job_links = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # ── Step 1: Collect job links from search results ──────────────
        for term in SEARCH_TERMS:
            search_url = f"{BASE_URL}/?s={term.replace(' ', '+')}"
            print(f"\n[scraper] Searching: {search_url}")
            await page.goto(search_url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # Try multiple selectors for job listing links
            links = await page.eval_on_selector_all(
                "a[href*='/jobs/'], a[href*='/job/'], .job-title a, h2 a, h3 a, .entry-title a",
                "els => els.map(el => ({href: el.href, text: el.innerText.trim()}))"
            )

            for link in links:
                href = link.get("href", "")
                text = link.get("text", "")
                if href and href not in [l["url"] for l in job_links]:
                    if any(kw in text.lower() for kw in ["product", "manager", "analyst", "pm "]):
                        job_links.append({"url": href, "title_hint": text})
                        print(f"  + Found: {text[:60]} → {href}")

        print(f"\n[scraper] Found {len(job_links)} job links. Fetching details...")

        # ── Step 2: Visit each job page and extract details ────────────
        jobs = []
        for i, link in enumerate(job_links):
            url = link["url"]
            print(f"\n[scraper] [{i+1}/{len(job_links)}] {url}")
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(1500)

                # Extract page text
                content = await page.inner_text("body")

                # Job title
                title = ""
                try:
                    title = await page.inner_text("h1")
                    title = title.strip()
                except:
                    title = link["title_hint"]

                # Company name — look for common patterns
                company = _extract_company(content, page)
                company = await company if asyncio.iscoroutine(company) else company

                # Email — scan full page text
                emails = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", content)
                # Filter out generic/noreply emails
                emails = [e for e in emails if not any(x in e.lower() for x in [
                    "noreply", "no-reply", "support@internsg", "info@internsg",
                    "admin@internsg", "example.com", "sentry"
                ])]
                email = emails[0] if emails else ""

                # Clean up job description
                jd_text = _clean_text(content)

                if title:
                    jobs.append({
                        "title": title,
                        "company": company,
                        "email": email,
                        "url": url,
                        "description": jd_text,
                    })
                    print(f"  Title:   {title}")
                    print(f"  Company: {company}")
                    print(f"  Email:   {email or '(not found)'}")

            except Exception as e:
                print(f"  [error] {e}")
                continue

        await browser.close()

    # ── Step 3: Save to jobs.csv and job_descriptions/ ─────────────────
    if not jobs:
        print("\n[scraper] No jobs found. Try adjusting search terms or selectors.")
        return

    os.makedirs(JD_DIR, exist_ok=True)

    # Load existing jobs to get the next ID
    existing = _load_existing_jobs()
    existing_urls = {j.get("contact_email", "") + j.get("role", "") for j in existing}
    next_id = _next_job_id(existing)

    new_jobs = []
    for job in jobs:
        # Skip duplicates
        key = job["email"] + job["title"]
        if key in existing_urls:
            print(f"[scraper] Skipping duplicate: {job['title']}")
            continue

        job_id = f"job_{next_id:03d}"
        jd_file = f"{job_id}.txt"
        jd_path = os.path.join(JD_DIR, jd_file)

        # Write job description file
        with open(jd_path, "w", encoding="utf-8") as f:
            f.write(f"Company: {job['company']}\n")
            f.write(f"Role: {job['title']}\n")
            f.write(f"Source: {job['url']}\n\n")
            f.write(job["description"])

        new_jobs.append({
            "id": job_id,
            "company": job["company"],
            "role": job["title"],
            "contact_email": job["email"],
            "job_description_file": jd_file,
            "variant_id": "",
            "status": "pending",
            "sent_at": "",
            "follow_up_at": "",
            "follow_up_sent_at": "",
            "replied_at": "",
            "message_id": "",
        })

        existing_urls.add(key)
        next_id += 1

    # Append to jobs.csv
    fieldnames = [
        "id", "company", "role", "contact_email", "job_description_file",
        "variant_id", "status", "sent_at", "follow_up_at",
        "follow_up_sent_at", "replied_at", "message_id",
    ]

    all_jobs = existing + new_jobs
    with open(JOBS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_jobs)

    print(f"\n[scraper] Done!")
    print(f"  Added {len(new_jobs)} new jobs to jobs.csv")
    print(f"  Job descriptions saved to job_descriptions/")

    if new_jobs:
        print(f"\n  New jobs:")
        for j in new_jobs:
            email_str = j['contact_email'] or '(no email found)'
            print(f"    {j['id']} | {j['company'][:25]:<25} | {j['role'][:35]:<35} | {email_str}")

    print(f"\n  Run: python3 engine.py  to start sending applications")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _extract_company(content: str, page) -> str:
    """Try to extract company name from page."""
    # Try structured selectors first
    for selector in [".company-name", ".employer", "[class*='company']", "[class*='employer']"]:
        try:
            el = await page.query_selector(selector)
            if el:
                text = await el.inner_text()
                if text.strip():
                    return text.strip()
        except:
            pass

    # Fallback: look for "Company:" pattern in text
    match = re.search(r"Company[:\s]+([A-Z][^\n]{2,50})", content)
    if match:
        return match.group(1).strip()

    # Fallback: look for "at [Company]" pattern in title
    match = re.search(r"\bat\s+([A-Z][A-Za-z0-9\s&.,'-]{2,40})", content[:500])
    if match:
        return match.group(1).strip()

    return "Unknown"


def _clean_text(text: str) -> str:
    """Clean up scraped text."""
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        line = line.strip()
        if line and len(line) > 3:
            cleaned.append(line)
    # Remove duplicate lines
    seen = set()
    deduped = []
    for line in cleaned:
        if line not in seen:
            seen.add(line)
            deduped.append(line)
    return "\n".join(deduped[:150])  # cap at 150 lines


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
    asyncio.run(scrape())
