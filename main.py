import json
import os
import re
import html

from supabase import create_client
from collectors.greenhouse import (
    fetch_greenhouse_jobs,
    normalize_greenhouse_job,
)


SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")


def load_greenhouse_boards():
    with open(
        "config/greenhouse_boards.json",
        "r",
        encoding="utf-8"
    ) as file:
        return json.load(file)


def clean_text(value):
    """Convert HTML-ish job content into searchable plain text."""
    if not value:
        return ""

    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def check_philippines_eligibility(job):
    """
    Return one of:
    publish - clear evidence PH applicants are eligible
    review  - potentially eligible, but geography is ambiguous
    reject  - location clearly doesn't establish PH eligibility
    """

    location = clean_text(job.get("location")).lower().strip()

    philippines_terms = [
        "philippines",
        "philippine",
        "metro manila",
        "manila",
        "makati",
        "taguig",
        "quezon city",
        "pasig",
        "cebu",
        "davao",
    ]

    if any(term in location for term in philippines_terms):
        return "publish", "Location explicitly allows Philippines"

    apac_terms = [
        "apac",
        "asia pacific",
        "asia-pacific",
        "southeast asia",
        "south east asia",
    ]

    if any(term in location for term in apac_terms):
        return "publish", "Location explicitly allows APAC/Asia applicants"

    worldwide_terms = [
        "worldwide",
        "anywhere",
        "global",
        "remote - global",
        "remote-global",
        "remote worldwide",
        "remote - worldwide",
    ]

    if any(term in location for term in worldwide_terms):
        return "publish", "Location explicitly allows worldwide applicants"

    generic_remote = [
        "remote",
        "fully remote",
        "remote - remote",
    ]

    if location in generic_remote or not location:
        return "review", "Remote/location eligibility is ambiguous"

    return "reject", f"No explicit Philippines eligibility: {job.get('location')}"


def classify_job(job):
    """
    Categorize primarily from the job title to avoid
    unrelated words in long descriptions causing false matches.
    """

    title = clean_text(job.get("title")).lower()

    categories = [
        ("Virtual Assistant", [
            "virtual assistant",
            "remote assistant",
        ]),

        ("Executive Assistant", [
            "executive assistant",
            "personal assistant",
            "administrative assistant",
            "admin assistant",
        ]),

        ("Customer Support", [
            "customer support",
            "customer service",
            "support specialist",
            "support representative",
            "customer success",
            "customer experience",
        ]),

        ("Sales", [
            "sales",
            "business development",
            "appointment setter",
            "lead generation",
            "account executive",
            "sdr",
            "bdr",
        ]),

        ("Marketing", [
            "marketing",
            "growth marketing",
            "seo",
            "email marketer",
        ]),

        ("Social Media", [
            "social media",
            "community manager",
            "content creator",
        ]),

        ("E-commerce", [
            "ecommerce",
            "e-commerce",
            "shopify",
            "amazon specialist",
        ]),

        ("Bookkeeping & Finance", [
            "bookkeeper",
            "bookkeeping",
            "accounting",
            "accounts payable",
            "accounts receivable",
            "finance",
            "payroll",
        ]),

        ("Recruitment & HR", [
            "recruiter",
            "recruitment",
            "talent acquisition",
            "human resources",
            "hr specialist",
            "hr coordinator",
            "people operations",
        ]),

        ("Design & Creative", [
            "graphic designer",
            "designer",
            "video editor",
            "motion designer",
        ]),

        ("Writing & Content", [
            "copywriter",
            "content writer",
            "writer",
            "editor",
        ]),

        ("Data Entry", [
            "data entry",
            "data encoder",
        ]),

        ("Operations & Admin", [
            "operations",
            "operations specialist",
            "operations coordinator",
            "project coordinator",
            "administrative",
        ]),
    ]

    for category, keywords in categories:
        if any(keyword in title for keyword in keywords):
            return category

    return "Other Remote"


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY must be configured."
        )

    supabase = create_client(
        SUPABASE_URL,
        SUPABASE_KEY
    )

    boards = load_greenhouse_boards()

    total_fetched = 0
total_published = 0
total_review = 0
total_rejected = 0

    for board_config in boards:
        company = board_config["company"]
        board = board_config["board"]

        print(f"\nChecking {company} ({board})...")

        try:
            raw_jobs = fetch_greenhouse_jobs(board)
        except Exception as error:
            print(f"  Failed: {error}")
            continue

        print(f"  Found {len(raw_jobs)} jobs.")
        total_fetched += len(raw_jobs)

        for raw_job in raw_jobs:
            job = normalize_greenhouse_job(
                raw_job,
                company=company,
                board=board,
            )

            decision, reason = check_philippines_eligibility(job)

if decision == "publish":
    total_published += 1

    job["philippines_eligible"] = True
    job["classification_reason"] = reason
    job["category"] = classify_job(job)

    try:
        (
            supabase.table("jobs")
            .upsert(
                job,
                on_conflict="source,source_job_id",
            )
            .execute()
        )

        print(
            f"  PUBLISHED: {job['title']} "
            f"[{job['category']}] "
            f"- {job['location']}"
        )

    except Exception as error:
        print(f"  Database error: {error}")

else:
    if decision == "review":
        total_review += 1
    else:
        total_rejected += 1

    review_record = {
        "title": job.get("title"),
        "company": job.get("company"),
        "location": job.get("location"),
        "source": job.get("source"),
        "source_job_id": job.get("source_job_id"),
        "job_url": job.get("job_url"),
        "decision": decision,
        "reason": reason,
    }

    try:
        (
            supabase.table("job_reviews")
            .upsert(
                review_record,
                on_conflict="source,source_job_id",
            )
            .execute()
        )

    except Exception as error:
        print(f"  Review database error: {error}")

   print("\n-----------------------------")
print("COLLECTION COMPLETE")
print("-----------------------------")
print(f"Fetched:   {total_fetched}")
print(f"Published: {total_published}")
print(f"Review:    {total_review}")
print(f"Rejected:  {total_rejected}")


if __name__ == "__main__":
    main()
