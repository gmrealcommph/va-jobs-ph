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
        encoding="utf-8",
    ) as file:
        return json.load(file)


def clean_text(value):
    if not value:
        return ""

    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def check_philippines_eligibility(job):
    """
    Return:
      publish = clear evidence Philippines applicants are eligible
      review  = potentially eligible, but location is ambiguous
      reject  = no evidence Philippines applicants are eligible
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
        return (
            "publish",
            "Location explicitly allows Philippines",
        )

    apac_terms = [
        "apac",
        "asia pacific",
        "asia-pacific",
        "southeast asia",
        "south east asia",
    ]

    if any(term in location for term in apac_terms):
        return (
            "publish",
            "Location explicitly allows APAC/Asia applicants",
        )

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
        return (
            "publish",
            "Location explicitly allows worldwide applicants",
        )

    generic_remote = [
        "remote",
        "fully remote",
        "remote - remote",
    ]

    if location in generic_remote or not location:
        return (
            "review",
            "Remote/location eligibility is ambiguous",
        )

    return (
        "reject",
        f"No explicit Philippines eligibility: {job.get('location')}",
    )

def check_va_relevance(job):
    """
    Determine whether a job belongs on a VA-focused
    remote jobs platform.

    Returns:
        relevant
        review
        irrelevant
    """

    title = clean_text(job.get("title")).lower()

    relevant_terms = [
        # Assistants / administration
        "virtual assistant",
        "executive assistant",
        "personal assistant",
        "administrative assistant",
        "admin assistant",
        "administrative coordinator",
        "office coordinator",

        # Customer support
        "customer support",
        "customer service",
        "customer success",
        "customer experience",
        "support specialist",
        "support representative",

        # Sales / lead generation
        "sales representative",
        "sales development",
        "business development",
        "account executive",
        "appointment setter",
        "lead generation",
        "lead generator",
        "sdr",
        "bdr",

        # Operations
        "operations assistant",
        "operations coordinator",
        "operations specialist",
        "project coordinator",

        # Marketing
        "marketing assistant",
        "marketing coordinator",
        "marketing specialist",
        "digital marketing",
        "email marketing",
        "seo specialist",

        # Social
        "social media",
        "community manager",
        "content creator",

        # Ecommerce
        "ecommerce",
        "e-commerce",
        "shopify",
        "amazon specialist",

        # Finance
        "bookkeeper",
        "bookkeeping",
        "accounts payable",
        "accounts receivable",
        "accounting assistant",

        # Recruitment
        "recruiter",
        "recruitment coordinator",
        "talent acquisition coordinator",
        "hr assistant",
        "hr coordinator",

        # Content / creative
        "copywriter",
        "content writer",
        "graphic designer",
        "video editor",

        # Data
        "data entry",
        "data encoder",
    ]

    if any(term in title for term in relevant_terms):
        return "relevant", "Title matches VA/remote-work role"

    irrelevant_terms = [
        "software engineer",
        "software developer",
        "devops",
        "site reliability",
        "cloud engineer",
        "field engineer",
        "solutions architect",
        "solution architect",
        "security engineer",
        "security researcher",
        "data scientist",
        "machine learning",
        "research scientist",
        "developer advocate",
        "kernel engineer",
        "linux engineer",
        "legal counsel",
        "attorney",
        "lawyer",
        "physician",
        "nurse",
        "clinical",
    ]

    if any(term in title for term in irrelevant_terms):
        return "irrelevant", "Specialist role outside VA job scope"

    return "review", "Role relevance requires review"

def classify_job(job):
    """
    Categorize primarily using the job title.

    This prevents random words inside a long job description
    from assigning an unrelated category.
    """

    title = clean_text(job.get("title")).lower()

    categories = [
        (
            "Virtual Assistant",
            [
                "virtual assistant",
                "remote assistant",
            ],
        ),
        (
            "Executive Assistant",
            [
                "executive assistant",
                "personal assistant",
                "administrative assistant",
                "admin assistant",
            ],
        ),
        (
            "Customer Support",
            [
                "customer support",
                "customer service",
                "support specialist",
                "support representative",
                "customer success",
                "customer experience",
            ],
        ),
        (
            "Sales",
            [
                "sales",
                "business development",
                "appointment setter",
                "lead generation",
                "account executive",
                "sdr",
                "bdr",
            ],
        ),
        (
            "Marketing",
            [
                "marketing",
                "growth marketing",
                "seo",
                "email marketer",
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
                "accounting",
                "accounts payable",
                "accounts receivable",
                "finance",
                "payroll",
            ],
        ),
        (
            "Recruitment & HR",
            [
                "recruiter",
                "recruitment",
                "talent acquisition",
                "human resources",
                "hr specialist",
                "hr coordinator",
                "people operations",
            ],
        ),
        (
            "Design & Creative",
            [
                "graphic designer",
                "designer",
                "video editor",
                "motion designer",
            ],
        ),
        (
            "Writing & Content",
            [
                "copywriter",
                "content writer",
                "writer",
                "editor",
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
                "operations specialist",
                "operations coordinator",
                "project coordinator",
                "administrative",
            ],
        ),
    ]

    for category, keywords in categories:
        if any(keyword in title for keyword in keywords):
            return category

    return "Other Remote"


def save_published_job(supabase, job, reason):
    job["philippines_eligible"] = True
    job["classification_reason"] = reason
    job["category"] = classify_job(job)

    (
        supabase.table("jobs")
        .upsert(
            job,
            on_conflict="source,source_job_id",
        )
        .execute()
    )


def save_review_job(supabase, job, decision, reason):
    record = {
        "title": job.get("title"),
        "company": job.get("company"),
        "location": job.get("location"),
        "source": job.get("source"),
        "source_job_id": job.get("source_job_id"),
        "job_url": job.get("job_url"),
        "decision": decision,
        "reason": reason,
    }

    (
        supabase.table("job_reviews")
        .upsert(
            record,
            on_conflict="source,source_job_id",
        )
        .execute()
    )


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY must be configured."
        )

    supabase = create_client(
        SUPABASE_URL,
        SUPABASE_KEY,
    )

    boards = load_greenhouse_boards()

    total_fetched = 0
    total_published = 0
    total_review = 0
    total_rejected = 0
    total_errors = 0

    for board_config in boards:
        company = board_config["company"]
        board = board_config["board"]

        print(f"\nChecking {company} ({board})...")

        try:
            raw_jobs = fetch_greenhouse_jobs(board)

        except Exception as error:
            print(f"  SOURCE FAILED: {error}")
            total_errors += 1
            continue

        print(f"  Found {len(raw_jobs)} jobs.")

        total_fetched += len(raw_jobs)

        for raw_job in raw_jobs:
            try:
                job = normalize_greenhouse_job(
                    raw_job,
                    company=company,
                    board=board,
                )

                decision, reason = check_philippines_eligibility(job)

                if decision == "publish":
                    relevance, relevance_reason = check_va_relevance(job)

                    if relevance == "relevant":
                        save_published_job(
                            supabase,
                            job,
                            reason,
                        )

                        total_published += 1

                        print(
                            f"  PUBLISHED: {job['title']} "
                            f"[{job['category']}] "
                            f"- {job['location']}"
                        )

                    else:
                        review_decision = (
                            "review"
                            if relevance == "review"
                            else "reject"
                        )

                        combined_reason = (
                            f"{relevance_reason}. "
                            f"Geography: {reason}"
                        )

                        save_review_job(
                            supabase,
                            job,
                            review_decision,
                            combined_reason,
                        )

                        if review_decision == "review":
                            total_review += 1
                        else:
                            total_rejected += 1

                elif decision == "review":
                    save_review_job(
                        supabase,
                        job,
                        decision,
                        reason,
                    )

                    total_review += 1

                else:
                    save_review_job(
                        supabase,
                        job,
                        decision,
                        reason,
                    )

                    total_rejected += 1

            except Exception as error:
                total_errors += 1

                print(
                    f"  JOB ERROR: "
                    f"{raw_job.get('title', 'Unknown')} "
                    f"- {error}"
                )

    print("\n================================")
    print("COLLECTION COMPLETE")
    print("================================")
    print(f"Fetched:   {total_fetched}")
    print(f"Published: {total_published}")
    print(f"Review:    {total_review}")
    print(f"Rejected:  {total_rejected}")
    print(f"Errors:    {total_errors}")
    print("================================")


if __name__ == "__main__":
    main()
