"""
scrape_only.py — Fetch LinkedIn jobs via Apify and save raw results to scraped_jobs.csv

Usage:
    python3 scrape_only.py
"""

import csv
import json
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_CSV = os.path.join(BASE_DIR, "scraped_jobs.csv")

SEARCH_URLS = [
    "https://www.linkedin.com/jobs/search/?keywords=product+manager&location=Singapore",
    "https://www.linkedin.com/jobs/search/?keywords=product+analyst&location=Singapore",
    "https://www.linkedin.com/jobs/search/?keywords=business+analyst&location=Singapore",
    "https://www.linkedin.com/jobs/search/?keywords=strategy+analyst&location=Singapore",
    "https://www.linkedin.com/jobs/search/?keywords=growth+manager&location=Singapore",
]
MAX_ITEMS_PER_QUERY = 30


def run():
    from apify_client import ApifyClient
    client = ApifyClient(os.environ["APIFY_API_KEY"])

    all_jobs = []
    seen_urls = set()

    for search_url in SEARCH_URLS:
        keyword = search_url.split("keywords=")[1].split("&")[0].replace("+", " ")
        print(f"\n[apify] Searching: '{keyword}' in Singapore ...")
        try:
            run_result = client.actor("curious_coder/linkedin-jobs-scraper").call(
                run_input={"urls": [search_url], "proxy": {"useApifyProxy": True}}
            )
            items = list(client.dataset(run_result["defaultDatasetId"]).iterate_items())
            count = 0
            for item in items[:MAX_ITEMS_PER_QUERY]:
                url = item.get("link") or ""
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_jobs.append({
                        "title": item.get("title", ""),
                        "company": item.get("companyName", ""),
                        "location": item.get("location", ""),
                        "posted_at": item.get("postedAt", ""),
                        "employment_type": item.get("employmentType", ""),
                        "seniority": item.get("seniorityLevel", ""),
                        "easy_apply": item.get("easyApply", ""),
                        "apply_url": item.get("applyUrl") or url,
                        "linkedin_url": url,
                        "company_website": item.get("companyWebsite", ""),
                        "description_preview": (item.get("descriptionText") or "")[:300],
                    })
                    count += 1
            print(f"  → {count} jobs added (total: {len(all_jobs)})")
        except Exception as e:
            print(f"  [error] {e}")

    if not all_jobs:
        print("\nNo jobs found.")
        return

    fieldnames = ["title", "company", "location", "posted_at", "employment_type",
                  "seniority", "easy_apply", "apply_url", "linkedin_url",
                  "company_website", "description_preview"]

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_jobs)

    print(f"\n✓ Saved {len(all_jobs)} jobs to scraped_jobs.csv")


if __name__ == "__main__":
    run()
