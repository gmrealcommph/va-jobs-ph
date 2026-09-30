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
    Determine whether there is reasonable evidence that someone
    living in the Philippines can apply.

    Explicit geographic restrictions take priority over generic
    remote/global wording in the description.
    """

    location = clean_text(job.get("location")).lower()
    description = clean_text(job.get("description")).lower()
    title = clean_text(job.get("title")).lower()

    # Strongest positive signal: Philippines is explicitly named.
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
        return True, "Location explicitly allows Philippines"

    # Explicit locations/regions that normally exclude PH applicants.
    restricted_location_terms = [
        "united states",
        "usa",
        "u.s.",
        "u.s. only",
        "us only",
        "canada",
        "united kingdom",
        "uk only",
        "france",
        "germany",
        "romania",
        "hungary",
        "bulgaria",
        "netherlands",
        "iberia",
        "poland",
        "australia",
        "new zealand",
        "malaysia",
        "singapore",
        "india",
        "south america",
        "latin america",
        "latam",
        "emea",
        "dach",
        "amer",
        "americas",
        "europe",
        "western europe",
    ]

    if any(term in location for term in restricted_location_terms):
        return False, f"Location appears geographically restricted: {job.get('location')}"

    # APAC can include the Philippines, provided there is no
    # contradictory country restriction.
    apac_terms = [
        "apac",
        "asia pacific",
        "asia-pacific",
        "asia pacific region",
    ]

    if any(term in location for term in apac_terms):
        return True, "Remote role open to APAC applicants"

    # Explicit worldwide/anywhere locations.
    worldwide_location_terms = [
        "worldwide",
        "anywhere",
        "global",
        "remote - global",
        "remote-global",
    ]

    if any(term in location for term in worldwide_location_terms):
        return True, "Location explicitly indicates worldwide/global remote"

    # If the description explicitly says Philippines, that's useful
    # provided the location itself did not already exclude PH.
    if any(term in description for term in philippines_terms):
        return True, "Job description explicitly references Philippines"

    # Strong worldwide wording in the description.
    worldwide_description_terms = [
        "work from anywhere",
        "work anywhere",
        "remote anywhere",
        "anywhere in the world",
        "anywhere worldwide",
        "globally distributed",
        "open worldwide",
        "worldwide applicants",
    ]

    if job.get("remote") and any(
        term in description
        for term in worldwide_description_terms
    ):
        return True, "Description explicitly indicates worldwide remote eligibility"

    return False, "No reliable evidence that Philippines-based applicants are eligible"


def classify_job(job):
    """
    Assign a practical category for the job board.
    """

    title = clean_text(job.get("title")).lower()
    description = clean_text(job.get("description")).lower()

    text = f"{title} {description}"

    categories = [
        (
            "Virtual Assistant",
            [
                "virtual assistant",
                "virtual executive assistant",
                "remote assistant",
            ],
        ),
        (
            "Executive Assistant",
            [
                "executive assistant",
                "personal assistant",
                "administrative assistant",
            ],
        ),
        (
            "Customer Support",
            [
                "customer support",
                "customer service",
                "customer success",
                "support specialist",
                "support representative",
            ],
        ),
        (
            "Sales",
            [
                "sales development",
                "sales representative",
                "business development",
                "appointment setter",
                "lead generation",
                "sales associate",
                "account executive",
            ],
        ),
        (
            "Marketing",
            [
                "marketing",
                "growth specialist",
                "growth manager",
                "seo",
                "email marketing",
            ],
        ),
        (
            "Social Media",
            [
                "social media",
                "community manager",
                "content creator",
            ],
        ),
        (
            "E-commerce",
            [
                "ecommerce",
                "e-commerce",
                "shopify",
                "amazon specialist",
            ],
        ),
        (
            "Bookkeeping & Finance",
            [
                "bookkeeper",
                "bookkeeping",
                "accounts payable",
                "accounts receivable",
                "accounting assistant",
                "finance assistant",
            ],
        ),
        (
            "Recruitment & HR",
            [
                "recruiter",
                "recruitment",
                "talent acquisition",
                "hr assistant",
                "human resources",
            ],
        ),
        (
            "Design",
            [
                "graphic designer",
                "web designer",
                "ui designer",
                "ux designer",
                "video editor",
            ],
        ),
        (
            "Writing & Content",
            [
                "copywriter",
                "content writer",
                "writer",
                "editor",
                "content specialist",
            ],
        ),
        (
            "Data Entry",
            [
                "data entry",
                "data encoder",
            ],
        ),
        (
            "Operations & Admin",
            [
                "operations",
                "coordinator",
                "administrator",
                "administrative",
                "project coordinator",
            ],
        ),
    ]

    for category, keywords in categories:
        if any(keyword in text for keyword in keywords):
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
    total_eligible = 0
    total_saved = 0

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

            eligible, reason = check_philippines_eligibility(job)

            if not eligible:
                continue

            total_eligible += 1

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

                total_saved += 1

                print(
                    f"  SAVED: {job['title']} "
                    f"[{job['category']}] "
                    f"- {job['location']}"
                )

            except Exception as error:
                print(
                    f"  Database error for "
                    f"{job['title']}: {error}"
                )

    print("\n-----------------------------")
    print("COLLECTION COMPLETE")
    print("-----------------------------")
    print(f"Fetched:  {total_fetched}")
    print(f"Eligible: {total_eligible}")
    print(f"Saved:    {total_saved}")


if __name__ == "__main__":
    main()
