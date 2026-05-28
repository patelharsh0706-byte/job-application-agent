"""
scrape_ncs_hr.py — Find NCS HR/hiring contacts from LinkedIn people search via Apify

Steps:
  1. Apify scrapes both LinkedIn people search pages for NCS HR/hiring profiles
  2. Hunter.io looks up emails at ncs.com.sg / ncsgroup.com per person
  3. Results saved to ncs_hr_contacts.csv

Usage:
    python3 scrape_ncs_hr.py
"""

import csv
import json
import os
import time
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_CSV = os.path.join(BASE_DIR, "ncs_hr_contacts.csv")

LINKEDIN_SEARCH_URLS = [
    "https://www.linkedin.com/search/results/people/?geoUrn=%5B%22102454443%22%5D&keywords=ncs%20hr%20hiring%20&origin=FACETED_SEARCH&sid=umN",
    "https://www.linkedin.com/search/results/people/?geoUrn=%5B%22102454443%22%5D&keywords=ncs%20hr%20hiring%20&origin=FACETED_SEARCH&page=2&sid=hU%3B",
]

NCS_DOMAINS = ["ncs.com.sg", "ncsgroup.com", "ncs.co"]

HUNTER_KEY = os.environ.get("hunter_api_key") or os.environ.get("HUNTER_API_KEY") or ""


def run():
    try:
        from apify_client import ApifyClient
    except ImportError:
        raise RuntimeError("Run: pip install apify-client")

    apify_token = os.environ.get("APIFY_API_KEY") or os.environ.get("APIFY_API_TOKEN")
    if not apify_token:
        raise RuntimeError("APIFY_API_KEY not found in .env")

    client = ApifyClient(apify_token)

    # ── Step 1: Scrape both LinkedIn pages via Apify ───────────────────────────
    profiles: list[dict] = []
    seen_urls: set[str] = set()

    for page_num, search_url in enumerate(LINKEDIN_SEARCH_URLS, 1):
        print(f"[apify] Scraping page {page_num} ...")
        items = _scrape_page(client, search_url)
        new = 0
        for item in items:
            name = _extract_name(item)
            title = _extract_title(item)
            profile_url = _extract_url(item)

            if not name:
                continue
            dedup_key = profile_url or name
            if dedup_key in seen_urls:
                continue
            seen_urls.add(dedup_key)

            profiles.append({
                "name": name,
                "title": title,
                "linkedin_url": profile_url,
                "email": "",
                "email_source": "",
            })
            new += 1
        print(f"  → {new} new profiles (total: {len(profiles)})\n")

    if not profiles:
        print("\n[!] No profiles returned.")
        print("    LinkedIn blocks unauthenticated scrapers.")
        print("    Add your LinkedIn li_at cookie to .env as LINKEDIN_COOKIE=<value>")
        print("    and re-run — the script will pass it to Apify automatically.\n")
        return

    print(f"[scraper] {len(profiles)} profiles found. Looking up emails...\n")

    # ── Step 2: Hunter.io bulk fetch + name match ─────────────────────────────
    if HUNTER_KEY:
        domain_emails = _fetch_domain_emails_bulk()
        for p in profiles:
            email, source = _match_email_for_person(p["name"], domain_emails)
            p["email"] = email
            p["email_source"] = source
            status = email or "(not found)"
            print(f"  {p['name'][:35]:<35} {p['title'][:30]:<30} → {status}")
            time.sleep(0.15)
    else:
        print("[warning] HUNTER_API_KEY not set — emails will be blank")

    # ── Step 3: Write CSV ─────────────────────────────────────────────────────
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["name", "title", "email", "email_source", "linkedin_url"],
        )
        writer.writeheader()
        writer.writerows(profiles)

    found = sum(1 for p in profiles if p["email"])
    print(f"\n{'='*65}")
    print(f"Done. {found}/{len(profiles)} contacts have emails.")
    print(f"Saved → {OUTPUT_CSV}")
    print(f"{'='*65}\n")

    print(f"{'Name':<30} {'Title':<30} {'Email'}")
    print(f"{'-'*30} {'-'*30} {'-'*35}")
    for p in profiles:
        print(f"{p['name'][:29]:<30} {p['title'][:29]:<30} {p['email'] or '—'}")


# ── Apify scraping ─────────────────────────────────────────────────────────────

NCS_ACTOR_INPUT = {
    "current_company": "NCS",
    "title": "hr",
    "geocode_location": "Singapore",
    "maxResults": 50,
    "proxy": {"useApifyProxy": True},
}

ACTORS = [
    ("powerai/linkedin-peoples-search-scraper", lambda url: NCS_ACTOR_INPUT),
]

_working_actor: str | None = None  # cache whichever actor works first


def _scrape_page(client, search_url: str) -> list[dict]:
    global _working_actor

    li_cookie = os.environ.get("LINKEDIN_COOKIE", "")
    actors_to_try = ACTORS if _working_actor is None else [
        (aid, bf) for aid, bf in ACTORS if aid == _working_actor
    ]

    for actor_id, build_input in actors_to_try:
        inp = build_input(search_url)
        if li_cookie:
            inp["cookie"] = li_cookie
            inp["cookies"] = [{"name": "li_at", "value": li_cookie}]

        print(f"  [trying actor] {actor_id}")
        try:
            run_result = client.actor(actor_id).call(run_input=inp)
            dataset_id = run_result.get("defaultDatasetId")
            items = list(client.dataset(dataset_id).iterate_items())
            if items:
                _working_actor = actor_id
                print(f"  [ok] {actor_id} returned {len(items)} items")
                return items
            print(f"  [empty] {actor_id} returned 0 items")
        except Exception as e:
            print(f"  [error] {actor_id}: {e}")

    return []


# ── Field extractors ───────────────────────────────────────────────────────────

def _extract_name(item: dict) -> str:
    return (
        item.get("full_name")
        or item.get("fullName")
        or f"{item.get('firstName', '')} {item.get('lastName', '')}".strip()
        or item.get("name", "")
    ).strip()


def _extract_title(item: dict) -> str:
    return (
        item.get("title")
        or item.get("headline")
        or item.get("jobTitle", "")
    ).strip()


def _extract_url(item: dict) -> str:
    return (
        item.get("url")
        or item.get("linkedInUrl")
        or item.get("profileUrl", "")
    ).strip()


# ── Hunter.io helpers ──────────────────────────────────────────────────────────

def _fetch_domain_emails_bulk() -> list[dict]:
    all_emails: list[dict] = []
    for domain in NCS_DOMAINS:
        url = (
            f"https://api.hunter.io/v2/domain-search"
            f"?domain={domain}&limit=100&api_key={HUNTER_KEY}"
        )
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
            emails = data.get("data", {}).get("emails", [])
            for e in emails:
                e["_domain"] = domain
            all_emails.extend(emails)
            print(f"  [hunter] {domain} → {len(emails)} emails found")
        except Exception as ex:
            print(f"  [hunter] {domain} error: {ex}")
        time.sleep(0.3)
    print()
    return all_emails


def _match_email_for_person(full_name: str, domain_emails: list[dict]) -> tuple[str, str]:
    name_parts = full_name.lower().split()
    if not name_parts:
        return "", ""

    best_match = None
    best_score = 0

    for e in domain_emails:
        first = (e.get("first_name") or "").lower()
        last = (e.get("last_name") or "").lower()
        candidate_parts = [p for p in [first, last] if p]

        score = sum(
            1 for part in name_parts
            if any(part in cp or cp in part for cp in candidate_parts)
        )
        if score > best_score and score >= 1:
            best_score = score
            best_match = e

    if best_match:
        return best_match["value"], f"hunter/{best_match['_domain']}"
    return "", ""


if __name__ == "__main__":
    run()
