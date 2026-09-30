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
    Decide whether a geographically eligible job belongs on the
    Philippines-focused VA / remote-work platform.

    Returns:
        relevant   -> publish automatically
        review     -> potentially suitable but ambiguous
        irrelevant -> reject automatically
    """

    title = clean_text(job.get("title")).lower()

    # ---------------------------------------------------------
    # 1. HIGH-CONFIDENCE TARGET ROLES
    # ---------------------------------------------------------

    target_terms = [
        # Virtual / executive / administrative assistance
        "virtual assistant",
        "executive assistant",
        "personal assistant",
        "administrative assistant",
        "admin assistant",
        "administrative coordinator",
        "admin coordinator",
        "office coordinator",
        "office assistant",
        "remote assistant",

        # Customer service / customer support
        "customer support",
        "customer service",
        "customer experience",
        "customer care",
        "support specialist",
        "support representative",
        "support agent",
        "customer service representative",

        # Customer success
        "customer success",

        # Sales / business development
        "sales development representative",
        "sales development",
        "business development representative",
        "business development",
        "appointment setter",
        "lead generation",
        "lead generator",
        "sales representative",
        "inside sales",
        "sales associate",

        # Operations / coordination
        "operations assistant",
        "operations coordinator",
        "operations specialist",
        "project coordinator",
        "project assistant",
        "business operations coordinator",

        # Marketing
        "marketing assistant",
        "marketing associate",
        "marketing coordinator",
        "marketing specialist",
        "digital marketing",
        "email marketing",
        "seo specialist",
        "seo assistant",

        # Social media / community
        "social media",
        "community manager",
        "community specialist",
        "content creator",

        # E-commerce
        "ecommerce",
        "e-commerce",
        "shopify",
        "amazon specialist",
        "amazon virtual assistant",

        # Bookkeeping / finance support
        "bookkeeper",
        "bookkeeping",
        "accounting assistant",
        "accounts payable",
        "accounts receivable",
        "billing specialist",
        "payroll specialist",

        # Recruitment / HR
        "recruiter",
        "recruitment coordinator",
        "talent acquisition coordinator",
        "hr assistant",
        "hr coordinator",
        "hr specialist",
        "hr generalist",
        "human resources assistant",

        # Writing / content
        "copywriter",
        "content writer",
        "content editor",
        "blog writer",

        # Design / creative
        "graphic designer",
        "video editor",
        "motion designer",

        # Data
        "data entry",
        "data encoder",
        "data processor",
    ]

    # Abbreviations need word-boundary matching so we don't accidentally
    # match things such as "address" because it contains "sdr".
    abbreviation_patterns = [
        r"\bsdr\b",
        r"\bbdr\b",
    ]

    matches_target = (
        any(term in title for term in target_terms)
        or any(
            re.search(pattern, title)
            for pattern in abbreviation_patterns
        )
    )

    # ---------------------------------------------------------
    # 2. TECHNICAL / PROFESSIONAL ROLES WE DON'T WANT
    # ---------------------------------------------------------

    technical_exclusions = [
        # Engineering / development
        "engineer",
        "engineering",
        "software developer",
        "software development",
        "web developer",
        "frontend developer",
        "front-end developer",
        "backend developer",
        "back-end developer",
        "full stack",
        "full-stack",
        "golang",
        "python developer",
        "python engineer",
        "rust developer",
        "rust engineer",

        # Infrastructure / cloud
        "devops",
        "site reliability",
        "linux",
        "kernel",
        "cloud architect",
        "solutions architect",
        "solution architect",
        "systems architect",
        "openstack",
        "kubernetes",
        "containerization",
        "virtualisation",
        "virtualization",

        # Security
        "security engineer",
        "security researcher",
        "security operations",
        "cybersecurity",
        "threat intelligence",

        # Data / AI
        "data scientist",
        "machine learning",
        "mlops",
        "research scientist",

        # Legal
        "legal counsel",
        "general counsel",
        "attorney",
        "lawyer",

        # Medical / clinical
        "physician",
        "nurse",
        "clinical",

        # Highly technical relations / advocacy
        "developer relations",
        "developer advocate",
    ]

    if any(term in title for term in technical_exclusions):
        return (
            "irrelevant",
            "Technical/professional role outside VA job scope",
        )

    # ---------------------------------------------------------
    # 3. SENIOR LEADERSHIP EXCLUSIONS
    # ---------------------------------------------------------

    senior_terms = [
        "vice president",
        "vp ",
        "vp,",
        "director",
        "head of ",
        "principal ",
        "chief ",
        "senior manager",
        "team manager",
        "engineering manager",
    ]

    # Certain target roles legitimately use "manager".
    allowed_manager_terms = [
        "social media manager",
        "community manager",
        "account manager",
        "customer success manager",
        "marketing manager",
        "ecommerce manager",
        "e-commerce manager",
    ]

    is_allowed_manager = any(
        term in title
        for term in allowed_manager_terms
    )

    if (
        any(term in title for term in senior_terms)
        and not is_allowed_manager
    ):
        return (
            "irrelevant",
            "Senior leadership role outside target job scope",
        )

    # ---------------------------------------------------------
    # 4. CLEAR TARGET ROLE
    # ---------------------------------------------------------

    if matches_target:
        return (
            "relevant",
            "Title matches target VA/remote-work role",
        )

    # ---------------------------------------------------------
    # 5. BORDERLINE ROLES WORTH REVIEWING
    # ---------------------------------------------------------

    review_terms = [
        "project manager",
        "account executive",
        "sales executive",
        "sales manager",
        "sales specialist",
        "account specialist",
        "account coordinator",
        "account manager",
        "marketing manager",
        "operations manager",
        "business services",
        "mobility specialist",
        "technical author",
        "content specialist",
        "communications",
        "human resources",
        "talent acquisition",
    ]

    if any(term in title for term in review_terms):
        return (
            "review",
            "Potential remote-work role requires review",
        )

    # ---------------------------------------------------------
    # 6. EVERYTHING ELSE
    # ---------------------------------------------------------

    return (
        "irrelevant",
        "Role does not match target VA/remote-work categories",
    )

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
