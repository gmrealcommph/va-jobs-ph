import json
import os

from supabase import create_client
from collectors.greenhouse import (
    fetch_greenhouse_jobs,
    normalize_greenhouse_job,
)


SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")


def load_greenhouse_boards():
    with open("config/greenhouse_boards.json", "r", encoding="utf-8") as file:
        return json.load(file)


def is_potentially_ph_eligible(job):
    """
    First-pass eligibility filter.

    For now we're deliberately conservative:
    accept jobs whose location explicitly references the Philippines,
    or remote jobs with broad/global wording.

    We'll make this much smarter after validating ingestion.
    """

    location = (job.get("location") or "").lower()
    description = (job.get("description") or "").lower()

    philippines_terms = [
        "philippines",
        "philippine",
        "manila",
        "metro manila",
        "makati",
        "taguig",
        "cebu",
    ]

    global_remote_terms = [
        "worldwide",
        "anywhere",
        "global remote",
        "remote globally",
        "work from anywhere",
    ]

    if any(term in location for term in philippines_terms):
        return True, "Location explicitly references the Philippines"

    combined_text = f"{location} {description}"

    if any(term in combined_text for term in philippines_terms):
        return True, "Job description references the Philippines"

    if job.get("remote") and any(
        term in combined_text for term in global_remote_terms
    ):
        return True, "Remote job appears to allow worldwide applicants"

    return False, "No clear evidence that applicants in the Philippines are eligible"


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY must be configured."
        )

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

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

            eligible, reason = is_potentially_ph_eligible(job)

            if not eligible:
                continue

            total_eligible += 1

            job["philippines_eligible"] = True
            job["classification_reason"] = reason

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
                print(f"  SAVED: {job['title']}")

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
